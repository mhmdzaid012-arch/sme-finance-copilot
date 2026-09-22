"""
Single source of truth for every figure quoted outside the code.

The deck, the README, the technical and security documents all quote numbers
from the running system. Numbers typed by hand drift: that is exactly how the
deck ended up saying Amara makes EUR 800 a month while the tool said EUR 998.
So every quoted figure is computed here, written to docs/evidence/facts.json by
scripts/generate_evidence.py, read by the deck builder, and checked against the
documents by tests/test_consistency.py. A stale number is a failing test.
"""

from __future__ import annotations

import json
import statistics
from datetime import timedelta

from . import config
from .store import _load_transactions, get_seller, load_financing_catalog
from .tools.analysis import analyse_business
from .tools.financing import match_financing
from .tools.forecast import backtest, forecast_cashflow
from .tools.whatif import simulate, verify_financing_options

SELLERS = ["amara-prints", "kofi-coffee", "linas-ceramics", "techfix-parts"]


def eur(x: float) -> str:
    """The one currency format used in every document."""
    return ("-" if x < 0 else "") + f"EUR {abs(x):,.0f}"


def pretty_date(iso: str) -> str:
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    y, m, d = (int(p) for p in iso.split("-"))
    return f"{d} {months[m - 1]}"


def _hero() -> dict:
    ctx = get_seller("amara-prints")
    an = analyse_business(ctx)["headline_metrics"]
    fc = forecast_cashflow(ctx, 60)
    fi = fc["findings"]
    amount, days, lead = (fi["suggested_bridge_amount"], fi["suggested_bridge_days"],
                          fi["days_until_first_shortfall"])
    match = match_financing(ctx, amount, "working_capital", days, lead)
    in_time = [e for e in match["eligible"] if not e["too_slow"]]
    verified = verify_financing_options(ctx, in_time, amount, days)
    solving = [v for v in verified if v["verdict"] in ("fixes", "avoids_negative")]
    rec = solving[0] if solving else None
    rec_entry = next(e for e in match["eligible"] if rec and e["id"] == rec["id"]) if rec else None

    cheapest_overall = min(match["eligible"], key=lambda e: e["cost"]["cost_for_period"])
    mca = next((e for e in match["eligible"] if e["id"] == "swiftcash-mca"), None)
    bill = next(o for o in ctx.profile["scheduled_obligations"]
                if o["counterparty"] == fi["primary_drivers"][0]["counterparty"])

    return {
        "name": ctx.name,
        "monthly_revenue": round(ctx.metrics["avg_monthly_revenue"], 2),
        "monthly_cash_surplus": an["monthly_cash_surplus"],
        "bank_balance": ctx.metrics["bank_balance"],
        "platform_balance": ctx.metrics["platform_balance"],
        "trapped_days": an["cash_trapped_days_of_sales"],
        "payout_cadence_days": ctx.profile["payout_schedule"]["cadence_days"],
        "payout_hold_days": ctx.profile["payout_schedule"]["hold_days"],
        "bill_counterparty": bill["counterparty"],
        "bill_amount": bill["amount"],
        "bill_due": bill["due"],
        "first_negative_date": fi["first_negative_date"],
        "trough_balance": fi["trough_balance"],
        "trough_date": fi["trough_date"],
        "need_amount": amount,
        "need_days": days,
        "lead_days": lead,
        "balance_day_60": fc["series"][-1]["balance"],
        # Sampled every 3 days for the deck chart.
        "balance_series": [[r["date"][5:], r["balance"]]
                           for i, r in enumerate(fc["series"])
                           if i % 3 == 0 or i == len(fc["series"]) - 1],
        "cheapest_overall": {
            "name": cheapest_overall["name"],
            "cost": cheapest_overall["cost"]["cost_for_period"],
            "speed_days": cheapest_overall["speed_days"],
            "too_slow": cheapest_overall["too_slow"],
        },
        "recommended": {
            "name": rec_entry["name"],
            "cost": rec["cost"],
            "speed_days": rec_entry["speed_days"],
            "verdict": rec["verdict"],
            "days_below_buffer": rec["days_below_buffer"],
        } if rec else None,
        "mca": {
            "name": mca["name"],
            "cost": mca["cost"]["cost_for_period"],
            "speed_days": mca["speed_days"],
            "effective_apr": mca["cost"]["effective_apr"],
            "verdict": next((v["verdict"] for v in verified if v["id"] == mca["id"]), None),
        } if mca else None,
        "verified_options": verified,
    }


def _lina() -> dict:
    ctx = get_seller("linas-ceramics")
    match = match_financing(ctx, 3000, "working_capital", 60)
    return {
        "months_trading": ctx.profile["months_trading"],
        "refund_rate": ctx.metrics["refund_rate"],
        "eligible_names": [e["name"] for e in match["eligible"]],
        "eligible_count": match["eligible_count"],
        "cheapest_cost": min(e["cost"]["cost_for_period"] for e in match["eligible"]),
        "excluded_wrong_purpose": [w["name"] for w in match["excluded_wrong_purpose"]],
        "monthly_revenue": round(ctx.metrics["avg_monthly_revenue"], 2),
        "near_miss": [
            {"name": n["name"], "why_not": n["why_not"]} for n in match["near_miss"]
        ],
    }


def _accuracy() -> dict:
    rows = []
    for sid in SELLERS:
        for h in (30, 45, 60):
            rows.append(backtest(sid, config.AS_OF - timedelta(days=h), h))
    errs = [abs(r["adjusted_error_pct_of_monthly_revenue"]) for r in rows]
    stress_path = config.EVIDENCE_DIR / "stress_test.json"
    stress = json.loads(stress_path.read_text()) if stress_path.exists() else None
    hero30 = next(r for r in rows if r["seller_id"] == "amara-prints" and r["horizon_days"] == 30)
    return {
        "hero_backtest_30d": {
            "raw_error": hero30["absolute_error"],
            "undeclared_one_offs": hero30["undeclared_one_off_total"],
            "adjusted_error": hero30["adjusted_error"],
            "adjusted_pct_of_revenue": hero30["adjusted_error_pct_of_monthly_revenue"],
        },
        "consistency_mean_pct": round(statistics.mean(errs), 1),
        "consistency_worst_pct": round(max(errs), 1),
        "stress": stress,
    }


def _whatif_demo() -> dict:
    """The what-ifs shown in the deck, computed rather than described."""
    ctx = get_seller("amara-prints")
    fi = forecast_cashflow(ctx, 60)["findings"]
    amount, days = fi["suggested_bridge_amount"], fi["suggested_bridge_days"]
    supplier = fi["primary_drivers"][0]["counterparty"]
    hero = _hero()
    cases = [
        ("Pay the supplier 3 weeks later", {"delay_obligation": {"counterparty": supplier, "days": 21}}),
        ("Marketplace payouts arrive 3 days late", {"payout_delay_days": 3}),
        (f"Take {hero['recommended']['name']}",
         {"financing": {"product_id": next(v["id"] for v in hero["verified_options"]
                                           if v["name"] == hero["recommended"]["name"]),
                        "amount": amount, "days_needed": days}}),
        (f"Take {hero['mca']['name']}",
         {"financing": {"product_id": "swiftcash-mca", "amount": amount, "days_needed": days}}),
    ]
    rows, chart = [], None
    for label, params in cases:
        r = simulate(ctx, dict(params, horizon_days=60))
        rows.append({"label": label, "verdict": r["verdict"],
                     "headline": r["summary_lines"][0],
                     "trough_after": r["scenario"]["findings"]["trough_balance"]})
        if label.startswith(f"Take {hero['recommended']['name']}"):
            pick = lambda ser: [[p["date"][5:], p["balance"]] for i, p in enumerate(ser)
                                if i % 3 == 0 or i == len(ser) - 1]
            chart = {"label": label, "baseline": pick(r["baseline"]["series"]),
                     "scenario": pick(r["scenario"]["series"])}
    return {"trough_before": fi["trough_balance"], "rows": rows, "chart": chart}


def _planted_attack() -> str:
    return next(t.memo for t in _load_transactions() if "SYSTEM OVERRIDE" in t.memo)


def _risk_count() -> int:
    text = (config.DOCS_DIR / "SECURITY.md").read_text(encoding="utf-8")
    return sum(1 for line in text.splitlines() if line.startswith("### R"))


def build_facts(test_count: int | None = None) -> dict:
    return {
        "as_of": config.AS_OF.isoformat(),
        "counts": {
            "sellers": len(SELLERS),
            "products": len(load_financing_catalog()["products"]),
            "transactions": len(_load_transactions()),
            "tests": test_count,
        },
        "hero": _hero(),
        "whatif_demo": _whatif_demo(),
        "planted_attack": _planted_attack(),
        "security": {"languages": ["English", "Chinese", "Arabic", "German", "French", "Spanish"],
                     "known_risks": _risk_count()},
        "lina": _lina(),
        "accuracy": _accuracy(),
        "surplus_by_seller": {
            sid: analyse_business(get_seller(sid))["headline_metrics"]["monthly_cash_surplus"]
            for sid in SELLERS
        },
    }
