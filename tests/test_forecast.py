"""Forecaster tests: mechanics, conservation, determinism and measured accuracy."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import config
from app.store import detect_recurring, get_seller
from app.tools.forecast import backtest, forecast_cashflow, payout_state

CUTOFFS = [30, 45, 60]


def test_forecast_is_deterministic(amara):
    a = forecast_cashflow(amara, 60)
    b = forecast_cashflow(amara, 60)
    assert a["series"] == b["series"]
    assert a["findings"] == b["findings"]


def test_horizon_is_clamped(amara):
    assert forecast_cashflow(amara, 1)["horizon_days"] == 7
    assert forecast_cashflow(amara, 9999)["horizon_days"] == 180
    assert len(forecast_cashflow(amara, 30)["series"]) == 30


def test_series_balance_is_a_running_total(amara):
    """Each day's balance must equal the previous one plus that day's net flow."""
    f = forecast_cashflow(amara, 45)
    prev = f["opening_bank_balance"]
    for row in f["series"]:
        expected = prev + row["inflow_payout"] - row["outflow_variable"] - row["outflow_fixed"]
        assert row["balance"] == pytest.approx(expected, abs=0.02), row["date"]
        prev = row["balance"]


def test_rolling_reserve_does_not_leak_cash(kofi):
    """
    The platform's rolling reserve delays money, it does not confiscate it.
    Over a horizon long enough to contain many payout cycles, total payouts
    must account for essentially all net accrual bar at most one held reserve.
    """
    f = forecast_cashflow(kofi, 120)
    fee = f["assumptions"]["platform_fee_rate"]
    refund = f["assumptions"]["refund_rate"]
    reserve = f["assumptions"]["payout_reserve_pct"]

    projected_net = sum(r["projected_sales"] for r in f["series"]) * (1 - fee - refund)
    paid_out = sum(p["amount"] for p in f["payout_events"])

    # Payouts also release accrual that existed before the horizon began, so
    # allow for the opening platform balance; the residual must be small.
    residual = projected_net + f["opening_platform_balance"] - paid_out
    one_cycle = projected_net / (120 / f["assumptions"]["payout_cadence_days"])
    assert residual < one_cycle * (1 + reserve) * 2.5, (
        f"residual {residual:.0f} too large vs one cycle {one_cycle:.0f}"
    )
    assert paid_out > 0


def test_payout_state_is_derived_from_history_not_the_generator(amara):
    """
    payout_state must work for an arbitrary as_of, which is what makes the
    forecaster backtestable. Earlier as_of dates must release strictly less.
    """
    fee, refund = amara.metrics["platform_fee_rate"], amara.metrics["refund_rate"]
    late, _ = payout_state(amara, fee, refund)

    earlier_ctx = get_seller("amara-prints", as_of=config.AS_OF - timedelta(days=40))
    early, _ = payout_state(earlier_ctx, fee, refund)

    assert late is not None and early is not None
    assert early < late


def test_scheduled_obligation_appears_in_series(amara):
    """A declared future bill must land on its date, at its amount."""
    f = forecast_cashflow(amara, 60)
    due = "2026-09-25"
    row = next(r for r in f["series"] if r["date"] == due)
    names = [e["counterparty"] for e in row["events"]]
    assert "Textil Nord GmbH" in names
    amount = next(e["amount"] for e in row["events"] if e["counterparty"] == "Textil Nord GmbH")
    assert amount == pytest.approx(6800.0)


def test_amara_shortfall_is_detected_with_lead_time(amara):
    f = forecast_cashflow(amara, 60)
    fi = f["findings"]
    assert fi["goes_negative"] is True
    assert fi["shortfall_to_buffer"] > 0
    assert fi["suggested_bridge_days"] > 0
    # Lead time must be positive and consistent with the first breach date.
    lead = fi["days_until_first_shortfall"]
    assert lead is not None and lead > 0
    breach = date.fromisoformat(fi["first_below_buffer_date"])
    assert (breach - amara.as_of).days == lead


def test_driver_attribution_finds_the_real_cause(amara):
    """
    The trough is weeks after the payment that causes it, so drivers must be
    attributed across the whole drawdown - not a window near the low point.
    """
    f = forecast_cashflow(amara, 60)
    drivers = f["findings"]["primary_drivers"]
    assert drivers, "expected driver attribution"
    assert drivers[0]["counterparty"] == "Textil Nord GmbH"
    assert drivers[0]["amount"] == pytest.approx(6800.0)


def test_healthy_seller_has_no_shortfall(lina):
    fi = forecast_cashflow(lina, 60)["findings"]
    assert fi["goes_negative"] is False
    assert fi["shortfall_to_buffer"] == 0
    assert fi["days_until_first_shortfall"] is None


def test_recurring_detection_finds_stable_costs_only(amara):
    rec = detect_recurring(amara)
    names = {r["counterparty"] for r in rec}
    assert "Studio Rent (Kreuzberg)" in names
    assert "Part-time Studio Assistant" in names
    # Per-order variable costs must never be classified as recurring bills,
    # or they would be double-counted against the sales-linked projection.
    assert not {"Supplier / Fulfilment", "Courier", "Ad Platform"} & names
    for r in rec:
        assert r["occurrences"] >= config.RECURRING_MIN_OCCURRENCES
        assert r["gap_stddev_days"] <= config.RECURRING_MAX_GAP_STDDEV_DAYS


@pytest.mark.parametrize("horizon", CUTOFFS)
@pytest.mark.parametrize("seller_id", ["amara-prints", "kofi-coffee",
                                       "linas-ceramics", "techfix-parts"])
def test_backtest_accuracy_within_declared_bounds(seller_id, horizon):
    """
    Measured accuracy, normalised against monthly revenue (the fair denominator
    across sellers of very different sizes). The bound asserted here is the one
    quoted in docs/TECHNICAL.md - if the method regresses, this fails.
    """
    cutoff = config.AS_OF - timedelta(days=horizon)
    b = backtest(seller_id, cutoff, horizon)
    err = abs(b["adjusted_error_pct_of_monthly_revenue"])
    assert err <= 10.0, (
        f"{seller_id} @ {horizon}d: adjusted error {err:.1f}% of monthly revenue"
    )


def test_backtest_isolates_undeclared_one_offs():
    """
    Amara's raw error is dominated by a EUR 4,500 one-off that was neither
    recurring nor declared. The backtest must identify it rather than silently
    absorbing it, because that gap is the method's headline limitation.
    """
    cutoff = config.AS_OF - timedelta(days=30)
    b = backtest("amara-prints", cutoff, 30)
    assert b["undeclared_one_off_total"] == pytest.approx(4500.0)
    assert abs(b["adjusted_error"]) < abs(b["absolute_error"])
    counterparties = {o["counterparty"] for o in b["undeclared_one_offs"]}
    assert "Textil Nord GmbH" in counterparties


def test_assumptions_are_reported(any_seller):
    """Every projection must ship the assumptions needed to audit it."""
    a = forecast_cashflow(any_seller, 30)["assumptions"]
    for key in ("growth_factor_per_28d", "platform_fee_rate", "refund_rate",
                "variable_cost_rates", "payout_hold_days", "method"):
        assert key in a
    lo, hi = config.TREND_CLAMP
    assert lo <= a["growth_factor_per_28d"] <= hi
