"""
Regression tests for the audit findings fixed on the finals branch.

Each block pins one finding from the October audit (A2, A3, A4, A5, B2, B4, B6,
B10) or from the finals review (N1). Every test here failed before its fix.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from app import config
from app.store import SellerContext, Transaction, compute_metrics, get_seller
from app.tools.alerts import generate_alerts
from app.tools.forecast import Scenario, forecast_cashflow


def _with_profile_copy(seller_id: str) -> SellerContext:
    """A seller whose profile can be edited without touching the cached data."""
    ctx = get_seller(seller_id)
    ctx.profile = copy.deepcopy(ctx.profile)
    return ctx


def _with_extra_txns(ctx: SellerContext, extra: list[Transaction]) -> SellerContext:
    out = SellerContext(profile=ctx.profile, transactions=list(ctx.transactions) + extra,
                        as_of=ctx.as_of)
    out.metrics = compute_metrics(out)
    return out


# ---------------------------------------------------------------------------
# A2 - a bill due today, or overdue and unpaid, must not disappear
# ---------------------------------------------------------------------------

URGENT = {"amount": 2000.0, "counterparty": "Urgent Bill", "category": "tax", "note": ""}


@pytest.mark.parametrize("days_ago", [0, 3, 20], ids=["due-today", "3-days-overdue", "20-days-overdue"])
def test_unpaid_bill_due_today_or_overdue_is_charged_on_day_one(days_ago):
    baseline = forecast_cashflow(get_seller("amara-prints"), 60)
    ctx = _with_profile_copy("amara-prints")
    due = config.AS_OF - timedelta(days=days_ago)
    ctx.profile["scheduled_obligations"].append(dict(URGENT, due=due.isoformat()))
    f = forecast_cashflow(ctx, 60)

    bill = next(o for o in f["scheduled_obligations"] if o["counterparty"] == "Urgent Bill")
    assert bill["date"] == (config.AS_OF + timedelta(days=1)).isoformat()
    assert bill["overdue"] is True
    assert due.isoformat() in bill["note"]
    # The whole path is EUR 2,000 lower from the first day.
    assert f["series"][0]["balance"] == pytest.approx(baseline["series"][0]["balance"] - 2000.0, abs=0.01)
    assert f["findings"]["trough_balance"] == pytest.approx(
        baseline["findings"]["trough_balance"] - 2000.0, abs=0.01)


def test_overdue_bill_already_paid_in_the_ledger_is_not_charged_again():
    baseline = forecast_cashflow(get_seller("amara-prints"), 60)
    ctx = _with_profile_copy("amara-prints")
    due = config.AS_OF - timedelta(days=3)
    ctx.profile["scheduled_obligations"].append(dict(URGENT, due=due.isoformat()))
    # Paid two days early. Opening balance is raised by the same amount so the
    # starting position is identical to the baseline.
    ctx.profile["opening_bank_balance"] += 2000.0
    ctx = _with_extra_txns(ctx, [Transaction(
        "paid-1", ctx.seller_id, due - timedelta(days=2), "bank", "expense", "tax",
        -2000.0, "Urgent Bill", "paid")])
    f = forecast_cashflow(ctx, 60)
    assert not any(o["counterparty"] == "Urgent Bill" for o in f["scheduled_obligations"])
    assert f["findings"]["trough_balance"] == pytest.approx(
        baseline["findings"]["trough_balance"], abs=0.01)


def test_future_bills_are_not_marked_overdue(any_seller):
    f = forecast_cashflow(any_seller, 60)
    assert f["scheduled_obligations"]
    assert not any(o["overdue"] for o in f["scheduled_obligations"])


# ---------------------------------------------------------------------------
# B6 - a payout delayed past the last forecast day is pending, not deleted
# ---------------------------------------------------------------------------

def test_baseline_forecast_has_no_pending_payouts(any_seller):
    assert forecast_cashflow(any_seller, 60)["payouts_pending_at_horizon"] == []


@pytest.mark.parametrize("seller_id,horizon,delay", [
    ("amara-prints", 53, 3), ("linas-ceramics", 90, 3),
    ("kofi-coffee", 90, 7), ("techfix-parts", 90, 7),
])
def test_delayed_payout_past_the_horizon_is_reported_as_pending(seller_id, horizon, delay):
    """Every euro the baseline pays out is either paid or pending in the scenario."""
    ctx = get_seller(seller_id)
    base = forecast_cashflow(ctx, horizon)
    late = forecast_cashflow(ctx, horizon, Scenario(payout_delay_days=delay))
    paid_base = sum(p["amount"] for p in base["payout_events"])
    paid_late = sum(p["amount"] for p in late["payout_events"])
    pending = late["payouts_pending_at_horizon"]
    assert pending, "this case was chosen because a payout crosses the horizon"
    assert paid_late + sum(p["amount"] for p in pending) == pytest.approx(paid_base, abs=0.05)
    horizon_end = (ctx.as_of + timedelta(days=horizon)).isoformat()
    assert all(p["date"] > horizon_end for p in pending)


def test_whatif_reply_says_the_delayed_payout_is_late_not_lost():
    from app.tools.whatif import simulate
    r = simulate(get_seller("amara-prints"), {"payout_delay_days": 3, "horizon_days": 53})
    pending = r["comparison"]["payouts_pending_at_horizon"]
    assert pending > 0
    text = " ".join(r["summary_lines"])
    assert "late, not lost" in text
    assert f"EUR {pending:,.0f}" in text


def test_whatif_reply_is_unchanged_when_nothing_is_pending():
    from app.tools.whatif import simulate
    r = simulate(get_seller("amara-prints"), {"payout_delay_days": 3, "horizon_days": 60})
    assert r["comparison"]["payouts_pending_at_horizon"] == 0
    assert "late, not lost" not in " ".join(r["summary_lines"])
