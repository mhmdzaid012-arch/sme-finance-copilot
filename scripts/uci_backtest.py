"""
Real-data test of the SALES forecast, on data this team did not generate.

    python scripts/uci_download.py     # once: downloads and cleans the data
    python scripts/uci_backtest.py     # writes docs/evidence/uci_backtest.json

Data: UCI "Online Retail II" (Chen, D., 2012, https://doi.org/10.24432/C5CG6D,
CC BY 4.0), a UK online gift-ware retailer, 1 Dec 2009 - 9 Dec 2011.

What this tests, and what it does not
-------------------------------------
The sandbox backtest is circular: the ledger was generated with the same
weekday pattern and seasonal table the forecaster assumes. This script runs
the forecaster's sales projection, unchanged and untuned, on a real retailer's
daily sales, and compares it with naive forecasts that need no model at all.

It tests the sales component only. The dataset has no payouts, fees, bills or
bank balances, so it says nothing about the payout model, which is the part of
the product that matters most.

Method
------
Rolling origins: one forecast every 7 days. Each forecast sees only the days
up to its origin and is scored on the following 14, 30 and 60 days. Nothing is
fitted to this dataset, so every scored day is held out.

Forecasts compared
  model           the product's own projection (app/tools/forecast.py):
                  weekday baseline x growth x monthly seasonal table
  last_week       each day = the same weekday in the last observed week
  weekday_avg_8w  each day = the mean of that weekday over the last 8 weeks
  last_year       each day = the same weekday 52 weeks (364 days) earlier

Two error measures, both as a share of actual sales over the horizon
  total_error     |forecast total - actual total| / actual total
                  (what matters for cash: was the total right?)
  daily_error     sum of |forecast - actual| per day / actual total
                  (was each day right?)
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.store import SellerContext, Transaction, compute_metrics  # noqa: E402
from app.tools.forecast import forecast_cashflow  # noqa: E402

DAILY_PATH = ROOT / "data" / "external" / "uci_online_retail_ii_daily.csv"
OUT_PATH = ROOT / "docs" / "evidence" / "uci_backtest.json"

HORIZONS = (14, 30, 60)
STEP_DAYS = 7
MIN_HISTORY_DAYS = 120          # the product needs 56 + 28 days; allow a margin
YEAR_DAYS = 364                 # 52 weeks, so weekdays line up
CATEGORY = "general_retail"     # not in SEASONALITY_DAMPING: full seasonal table
METHODS = ("model", "last_week", "weekday_avg_8w", "last_year")


def load_daily() -> dict[date, float]:
    if not DAILY_PATH.exists():
        raise SystemExit("Run `python scripts/uci_download.py` first.")
    with DAILY_PATH.open(newline="", encoding="utf-8") as fh:
        return {date.fromisoformat(r["date"]): float(r["sales_gbp"]) for r in csv.DictReader(fh)}


def model_forecast(sales: dict[date, float], origin: date, horizon: int) -> list[float]:
    """The product's own sales projection, called through forecast_cashflow."""
    txns = [Transaction(f"uci-{d.isoformat()}", "uci", d, "platform", "sale", "sales",
                        v, "Orders", "")
            for d, v in sales.items() if d <= origin and v > 0]
    profile = {
        "seller_id": "uci", "name": "UCI Online Retail II", "category": CATEGORY,
        "currency": "GBP", "months_trading": 24, "opening_bank_balance": 0.0,
        "scheduled_obligations": [],
        "payout_schedule": {"cadence_days": 14, "anchor": min(sales).isoformat(),
                            "hold_days": 10, "reserve_pct": 0.0},
    }
    ctx = SellerContext(profile=profile, transactions=txns, as_of=origin)
    ctx.metrics = compute_metrics(ctx)
    return [r["projected_sales"] for r in forecast_cashflow(ctx, horizon)["series"]]


def naive_forecasts(sales: dict[date, float], origin: date, horizon: int) -> dict[str, list[float] | None]:
    days = [origin + timedelta(days=i) for i in range(1, horizon + 1)]
    # Same weekday in the last observed week: step back whole weeks until on or before origin.
    last_week = []
    weekday_avg = []
    for d in days:
        back = d
        while back > origin:
            back -= timedelta(days=7)
        last_week.append(sales[back])
        weekday_avg.append(statistics.mean(sales[back - timedelta(days=7 * k)] for k in range(8)))
    first = min(sales)
    last_year = ([sales[d - timedelta(days=YEAR_DAYS)] for d in days]
                 if days[0] - timedelta(days=YEAR_DAYS) >= first else None)
    return {"last_week": last_week, "weekday_avg_8w": weekday_avg, "last_year": last_year}


def score(forecast: list[float], actual: list[float]) -> tuple[float, float]:
    total = sum(actual)
    return (abs(sum(forecast) - total) / total * 100,
            sum(abs(f - a) for f, a in zip(forecast, actual)) / total * 100)


def summarise(rows: list[dict]) -> dict:
    out = {}
    for h in HORIZONS:
        sub = [r for r in rows if r["horizon"] == h]
        out[str(h)] = {"origins": len(sub)}
        for m in METHODS:
            tot = [r[m][0] for r in sub if r[m] is not None]
            day = [r[m][1] for r in sub if r[m] is not None]
            if not tot:
                continue
            out[str(h)][m] = {
                "total_error_mean_pct": round(statistics.mean(tot), 1),
                "total_error_median_pct": round(statistics.median(tot), 1),
                "daily_error_mean_pct": round(statistics.mean(day), 1),
            }
        base = [r for r in sub if all(r[m] is not None for m in METHODS)]
        out[str(h)]["model_beats_on_total_error_pct_of_origins"] = {
            m: round(100 * sum(1 for r in base if r["model"][0] < r[m][0]) / len(base), 1)
            for m in METHODS[1:]} if base else {}
    return out


def main() -> dict:
    sales = load_daily()
    first, last = min(sales), max(sales)
    rows = []
    origin = first + timedelta(days=MIN_HISTORY_DAYS)
    while origin + timedelta(days=max(HORIZONS)) <= last:
        naive60 = naive_forecasts(sales, origin, max(HORIZONS))
        model60 = model_forecast(sales, origin, max(HORIZONS))
        actual60 = [sales[origin + timedelta(days=i)] for i in range(1, max(HORIZONS) + 1)]
        for h in HORIZONS:
            row = {"origin": origin.isoformat(), "horizon": h,
                   "model": score(model60[:h], actual60[:h])}
            for m, f in naive60.items():
                row[m] = score(f[:h], actual60[:h]) if f is not None else None
            rows.append(row)
        origin += timedelta(days=STEP_DAYS)

    second_year = [r for r in rows if r["last_year"] is not None]
    peak = [r for r in second_year if date.fromisoformat(r["origin"]).month in (9, 10)]
    out = {
        "dataset": {
            "name": "Online Retail II", "author": "Chen, D. (2012)",
            "source": "UCI Machine Learning Repository",
            "doi": "https://doi.org/10.24432/C5CG6D", "licence": "CC BY 4.0",
            "first_day": first.isoformat(), "last_day": last.isoformat(),
            "calendar_days": len(sales),
            "days_with_no_sales": sum(1 for v in sales.values() if v == 0),
        },
        "scope": ("Sales component only. The dataset has no payouts, fees, bills or bank "
                  "balances, so it does not test the payout model."),
        "method": {
            "rolling_origin_step_days": STEP_DAYS, "min_history_days": MIN_HISTORY_DAYS,
            "horizons_days": list(HORIZONS), "fitted_to_this_dataset": "nothing",
            "seasonal_table": "config.SEASONALITY, unchanged (written for the sandbox)",
            "errors": "percent of actual sales over the horizon; mean over origins",
        },
        "all_origins": summarise(rows),
        "origins_with_a_year_of_history": summarise(second_year),
        "origins_in_september_and_october_2011": summarise(peak),
    }
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")

    for label, key in (("ALL ORIGINS", "all_origins"),
                       ("ORIGINS WITH A YEAR OF HISTORY (last_year available)",
                        "origins_with_a_year_of_history"),
                       ("ORIGINS IN SEP-OCT 2011 (forecasting into the Christmas peak)",
                        "origins_in_september_and_october_2011")):
        print(f"\n{label}")
        print(f"{'horizon':>8} {'origins':>8} " + " ".join(f"{m:>22}" for m in METHODS))
        for h in HORIZONS:
            s = out[key][str(h)]
            cells = [f"{s[m]['total_error_mean_pct']:5.1f} ({s[m]['total_error_median_pct']:4.1f}) / "
                     f"{s[m]['daily_error_mean_pct']:5.1f}" if m in s else "-" for m in METHODS]
            print(f"{h:>7}d {s['origins']:>8} " + " ".join(f"{c:>22}" for c in cells))
            wins = s["model_beats_on_total_error_pct_of_origins"]
            if wins:
                print(" " * 18 + "model has the smaller total error in: "
                      + ", ".join(f"{v:.0f}% of origins vs {k}" for k, v in wins.items()))
    print("\ncells: total-sales error %, mean (median) / daily error %, mean. Lower is better.")
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")
    return out


if __name__ == "__main__":
    main()
