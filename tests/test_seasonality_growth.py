"""
Regression tests for the seasonality double-count (audit B1 / risk R12).

The growth rate used to be measured on raw sales, which still contain the
seasonal step (October 1.12 -> November 1.34), and the seasonal factor was then
applied a second time in the projection. These tests build synthetic sellers
whose true growth is known exactly, so the estimate can be checked against it.

No randomness: every synthetic history is a pure formula, so the tolerances
below are tight and the tests are deterministic.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import config
from app.store import SellerContext, Transaction, compute_metrics
from app.tools.forecast import _growth_factor, _seasonal, forecast_cashflow

CATEGORY = "apparel_print_on_demand"  # full (undamped) seasonality
WEEKDAY_WEIGHTS = [1.15, 1.10, 1.05, 1.10, 1.25, 0.95, 0.75]
BASE = 300.0
HISTORY_DAYS = 200


def true_sales(d: date, as_of: date, growth_per_28d: float, category: str = CATEGORY) -> float:
    """The synthetic seller's sales on any day, past or future."""
    trend = growth_per_28d ** ((d - as_of).days / config.TREND_WINDOW_DAYS)
    return BASE * WEEKDAY_WEIGHTS[d.weekday()] * trend * _seasonal(d, category)


def synthetic_seller(as_of: date, growth_per_28d: float = 1.0,
                     category: str = CATEGORY) -> SellerContext:
    """A seller with sales only: known trend, known seasonality, no noise."""
    txns = []
    for i in range(HISTORY_DAYS, -1, -1):
        d = as_of - timedelta(days=i)
        txns.append(Transaction(
            txn_id=f"syn-{i:04d}", seller_id="synthetic", date=d, ledger="platform",
            type="sale", category="sales",
            amount=round(true_sales(d, as_of, growth_per_28d, category), 2),
            counterparty="Marketplace Orders", memo=""))
    profile = {
        "seller_id": "synthetic", "name": "Synthetic", "category": category,
        "currency": "EUR", "months_trading": 24, "opening_bank_balance": 50_000.0,
        "safety_buffer": 1500.0, "scheduled_obligations": [],
        "payout_schedule": {
            "cadence_days": 14,
            "anchor": (as_of - timedelta(days=HISTORY_DAYS)).isoformat(),
            "hold_days": 10, "reserve_pct": 0.05,
        },
    }
    ctx = SellerContext(profile=profile, transactions=txns, as_of=as_of)
    ctx.metrics = compute_metrics(ctx)
    return ctx


NOVEMBER = date(2026, 11, 28)  # trend window = all of November, prior = October
JANUARY = date(2027, 1, 28)    # trend window = all of January, prior = December


# --- (a) seasonality but no trend -> growth must be 1.0 ----------------------

@pytest.mark.parametrize("as_of", [NOVEMBER, JANUARY], ids=["november", "january"])
def test_flat_seller_with_seasonality_has_no_growth(as_of):
    """
    Sales move only because of the calendar. Before the fix this returned
    1.1964 for November (the Oct->Nov seasonal step read as growth) and the
    0.80 floor for January.
    """
    assert _growth_factor(synthetic_seller(as_of, 1.0)) == pytest.approx(1.0, abs=0.002)


@pytest.mark.parametrize("category", ["food_and_beverage", "electronics_parts"])
def test_flat_seller_with_damped_seasonality_has_no_growth(category):
    ctx = synthetic_seller(NOVEMBER, 1.0, category)
    assert _growth_factor(ctx) == pytest.approx(1.0, abs=0.002)


# --- (b) a known underlying growth rate is recovered --------------------------

@pytest.mark.parametrize("as_of", [NOVEMBER, JANUARY, date(2026, 6, 15)],
                         ids=["november", "january", "june"])
@pytest.mark.parametrize("true_growth", [0.95, 1.03, 1.10])
def test_known_growth_is_recovered(as_of, true_growth):
    """Tolerance: within 0.005 of the true 28-day growth factor."""
    estimated = _growth_factor(synthetic_seller(as_of, true_growth))
    assert estimated == pytest.approx(true_growth, abs=0.005)


# --- (c) projections do not drift away from the truth -------------------------

def _projection_error(as_of: date, day: int) -> float:
    """Projected sales on `day` vs the seller's true sales, as a fraction."""
    ctx = synthetic_seller(as_of, 1.0)
    row = forecast_cashflow(ctx, 180)["series"][day - 1]
    truth = true_sales(as_of + timedelta(days=day), as_of, 1.0)
    return row["projected_sales"] / truth - 1.0


@pytest.mark.parametrize("as_of", [NOVEMBER, JANUARY], ids=["november", "january"])
@pytest.mark.parametrize("day", [60, 180])
def test_flat_seller_projection_does_not_drift(as_of, day):
    """
    A seller with no trend must be projected flat (seasonality aside). Before
    the fix the November projection was +46.9% too high at day 60 and +216.7%
    at day 180; January was -38.0% and -76.2%.
    """
    assert abs(_projection_error(as_of, day)) < 0.01


def test_seasonality_is_applied_exactly_once():
    """Day-by-day: projection == de-seasonalised baseline x that day's factor."""
    ctx = synthetic_seller(NOVEMBER, 1.0)
    for row in forecast_cashflow(ctx, 90)["series"]:
        d = date.fromisoformat(row["date"])
        expected = BASE * WEEKDAY_WEIGHTS[d.weekday()] * _seasonal(d, CATEGORY)
        assert row["projected_sales"] == pytest.approx(expected, rel=0.002), row["date"]
