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


# ---------------------------------------------------------------------------
# B10 - no alert may ever read "for roughly None days"
# ---------------------------------------------------------------------------

def _all_text(obj) -> str:
    import json
    return json.dumps(obj, default=str)


def test_no_alert_text_contains_none_even_with_a_negative_buffer():
    """A negative buffer means: negative balance, but nothing needed to reach the buffer."""
    ctx = _with_profile_copy("amara-prints")
    ctx.metrics = dict(ctx.metrics, safety_buffer=-10_000.0)
    f = forecast_cashflow(ctx, 60)
    assert f["findings"]["goes_negative"] and f["findings"]["suggested_bridge_days"] == 0
    alerts = generate_alerts(ctx, f, include_financing=False)
    for a in alerts["alerts"]:
        assert "None" not in a["headline"] + a["detail"], a["id"]


@pytest.mark.parametrize("horizon", [7, 30, 60, 180])
def test_no_alert_text_contains_none_for_any_seller(any_seller, horizon):
    alerts = generate_alerts(any_seller, forecast_cashflow(any_seller, horizon))
    for item in alerts["alerts"] + alerts["mitigations"]:
        assert "None" not in item.get("headline", "") + item.get("action", "") + item["detail"]


# ---------------------------------------------------------------------------
# A3 - several payments added together are never called "one payment"
# ---------------------------------------------------------------------------

def _monthly_cost_case():
    """Amara without her stock bill but with a large new monthly cost: the
    biggest driver is then the same payee paid several times."""
    ctx = _with_profile_copy("amara-prints")
    ctx.profile["scheduled_obligations"] = []
    f = forecast_cashflow(ctx, 120, Scenario(extra_monthly_cost=3000.0))
    return ctx, f


def test_drivers_say_how_many_payments_they_add_up():
    _, f = _monthly_cost_case()
    top = f["findings"]["primary_drivers"][0]
    trough = f["findings"]["trough_date"]
    events = [e for s in f["series"] if s["date"] <= trough for e in s["events"]
              if e["counterparty"] == top["counterparty"]]
    assert top["payments"] == len(events) > 1
    assert top["amount"] == pytest.approx(sum(e["amount"] for e in events))


def test_alert_does_not_call_several_payments_one_payment():
    ctx, f = _monthly_cost_case()
    top = f["findings"]["primary_drivers"][0]
    alerts = generate_alerts(ctx, f, include_financing=False)["alerts"]
    conc = next(a for a in alerts if a["id"] == "single_payment_concentration")
    assert "One payment" not in conc["headline"]
    assert f"{top['payments']} payments" in conc["headline"]
    assert "single obligation" not in conc["detail"]
    headline_alert = next(a for a in alerts if a["id"] == "cash_shortfall_critical")
    assert f"over {top['payments']} payments" in headline_alert["detail"]


def test_a_single_big_bill_is_still_called_one_payment(amara):
    f = forecast_cashflow(amara, 60)
    assert f["findings"]["primary_drivers"][0]["payments"] == 1
    conc = next(a for a in generate_alerts(amara, f, include_financing=False)["alerts"]
                if a["id"] == "single_payment_concentration")
    assert conc["headline"].startswith("One payment causes most of the squeeze")


# ---------------------------------------------------------------------------
# A4 - "47 days" (bridge span) and "43 days" (days below) are both explained
# ---------------------------------------------------------------------------

def test_bridge_span_and_days_below_are_both_reported_and_explained(amara):
    f = forecast_cashflow(amara, 60)
    fi = f["findings"]
    first = date.fromisoformat(fi["first_below_buffer_date"])
    last = date.fromisoformat(fi["last_below_buffer_date"])
    assert fi["suggested_bridge_days"] == (last - first).days + 1
    assert fi["days_below_buffer"] < fi["suggested_bridge_days"]
    detail = next(a for a in generate_alerts(amara, f, include_financing=False)["alerts"]
                  if a["id"] == "cash_shortfall_critical")["detail"]
    assert f"for roughly {fi['suggested_bridge_days']} days" in detail
    assert f"under the buffer on {fi['days_below_buffer']} of them" in detail


def test_financing_is_matched_on_the_bridge_span_not_the_days_below(amara):
    fi = forecast_cashflow(amara, 60)["findings"]
    alerts = generate_alerts(amara, forecast_cashflow(amara, 60))
    assert alerts["alerts"][0]["days_needed"] == fi["suggested_bridge_days"]


def test_no_span_note_when_the_two_counts_agree(kofi):
    f = forecast_cashflow(kofi, 60)
    assert f["findings"]["suggested_bridge_days"] == f["findings"]["days_below_buffer"]
    for a in generate_alerts(kofi, f, include_financing=False)["alerts"]:
        assert "of them" not in a["detail"]


# ---------------------------------------------------------------------------
# N1 - a payout that is due but has not reached the bank is still counted
# ---------------------------------------------------------------------------

def _without_last_bank_payout(seller_id: str) -> tuple[SellerContext, float]:
    """The same seller, in a world where the latest payout has not landed yet:
    it is missing from the bank ledger and from the bank balance."""
    ctx = get_seller(seller_id)
    last = max((t for t in ctx.transactions if t.type == "payout" and t.ledger == "bank"),
               key=lambda t: t.date)
    kept = [t for t in ctx.transactions
            if not (t.type == "payout" and t.date == last.date)]
    out = SellerContext(profile=ctx.profile, transactions=kept, as_of=ctx.as_of)
    out.metrics = compute_metrics(out)
    return out, last.amount


def test_on_time_sandbox_has_no_payout_in_transit_on_any_day(any_seller):
    """The schedule and the bank ledger agree on every day of the history."""
    from app.tools.forecast import payouts_in_transit
    m = any_seller.metrics
    start = date(2026, 4, 1)
    for i in range((config.AS_OF - start).days + 1):
        ctx = get_seller(any_seller.seller_id, as_of=start + timedelta(days=i))
        assert payouts_in_transit(ctx, m["platform_fee_rate"], m["refund_rate"]) == [], ctx.as_of


@pytest.mark.parametrize("seller_id", ["amara-prints", "techfix-parts"])
def test_late_payout_is_expected_instead_of_forgotten(seller_id):
    on_time = forecast_cashflow(get_seller(seller_id), 60)
    late_ctx, amount = _without_last_bank_payout(seller_id)
    late = forecast_cashflow(late_ctx, 60)

    assert late["opening_bank_balance"] == pytest.approx(on_time["opening_bank_balance"] - amount, abs=0.01)
    assert len(late["payouts_in_transit"]) == 1
    # The expected amount is rebuilt from sales and measured fee and refund
    # rates, so it matches the real payout to within 2%.
    assert late["payouts_in_transit"][0]["amount"] == pytest.approx(amount, rel=0.02)
    # Once the late payout lands, the two paths are the same again. Before the
    # fix the late path stayed a whole payout lower for the entire forecast.
    assert late["series"][-1]["balance"] == pytest.approx(
        on_time["series"][-1]["balance"], abs=amount * 0.02)


# ---------------------------------------------------------------------------
# B2 - monthly bills stay on their day of the month
# ---------------------------------------------------------------------------

def _projected_dates(f: dict, counterparty: str) -> list[date]:
    return [date.fromisoformat(s["date"]) for s in f["series"] for e in s["events"]
            if e["counterparty"] == counterparty]


def test_rent_stays_on_the_first_of_the_month_for_180_days(amara):
    """Before the fix: 2 Oct, 2 Nov, 3 Dec, 3 Jan, 3 Feb, 6 Mar."""
    dates = _projected_dates(forecast_cashflow(amara, 180), "Studio Rent (Kreuzberg)")
    assert dates == [date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1),
                     date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1)]


def test_bill_on_the_30th_uses_the_last_day_of_a_shorter_month(amara):
    dates = _projected_dates(forecast_cashflow(amara, 180), "Part-time Studio Assistant")
    assert dates == [date(2026, 9, 30), date(2026, 10, 30), date(2026, 11, 30),
                     date(2026, 12, 30), date(2027, 1, 30), date(2027, 2, 28)]


def test_every_monthly_bill_is_projected_once_per_month_on_its_day(any_seller):
    f = forecast_cashflow(any_seller, 120)
    for r in f["recurring_detected"]:
        assert r["monthly"], r["counterparty"]
        dates = _projected_dates(f, r["counterparty"])
        assert len({(d.year, d.month) for d in dates}) == len(dates), r["counterparty"]
        assert all(d.day == r["day_of_month"] for d in dates if d.month != 2), r["counterparty"]


def test_non_monthly_bills_still_repeat_on_their_day_gap():
    ctx = get_seller("amara-prints")
    weekly = [Transaction(f"wk-{i}", ctx.seller_id, config.AS_OF - timedelta(days=7 * i + 2),
                          "bank", "expense", "cleaning", -40.0, "Weekly Cleaner", "")
              for i in range(8)]
    f = forecast_cashflow(_with_extra_txns(ctx, weekly), 30)
    r = next(x for x in f["recurring_detected"] if x["counterparty"] == "Weekly Cleaner")
    assert r["monthly"] is False and r["cadence_days"] == 7
    dates = _projected_dates(f, "Weekly Cleaner")
    assert dates[0] == config.AS_OF + timedelta(days=5)
    assert all((b - a).days == 7 for a, b in zip(dates, dates[1:]))


# ---------------------------------------------------------------------------
# A5 - payout timing is named as a cause, with a figure
# ---------------------------------------------------------------------------

def test_payout_queue_is_a_running_total(any_seller):
    """queue(d) = queue(d-1) + that day's net sales - that day's payout."""
    f = forecast_cashflow(any_seller, 60)
    a = f["assumptions"]
    net_share = 1 - a["platform_fee_rate"] - a["refund_rate"]
    prev = f["opening_platform_balance"]
    for row in f["series"]:
        expected = prev + row["projected_sales"] * net_share - row["inflow_payout"]
        assert row["payout_queue"] == pytest.approx(expected, abs=0.02), row["date"]
        prev = row["payout_queue"]


def test_payout_hold_is_reported_at_the_low_point(amara):
    f = forecast_cashflow(amara, 60)
    hold = f["findings"]["payout_hold"]
    trough_row = next(r for r in f["series"] if r["date"] == f["findings"]["trough_date"])
    assert hold["held_at_trough"] == trough_row["payout_queue"]
    assert hold["trough_date"] == f["findings"]["trough_date"]
    # Amara's own held earnings exceed her gap: the thesis of the product.
    assert hold["covers_gap"] is True
    assert hold["held_at_trough"] > f["findings"]["shortfall_to_buffer"]


def test_headline_alert_names_payout_timing_with_the_amount(amara):
    f = forecast_cashflow(amara, 60)
    held = f["findings"]["payout_hold"]["held_at_trough"]
    detail = next(a for a in generate_alerts(amara, f, include_financing=False)["alerts"]
                  if a["id"] == "cash_shortfall_critical")["detail"]
    assert "Payout timing is the underlying cause" in detail
    assert f"EUR {held:,.0f}" in detail
    assert "more than the whole" in detail


def test_payout_timing_is_not_blamed_when_there_is_no_gap(lina):
    from app.tools.alerts import payout_hold_sentence
    f = forecast_cashflow(lina, 60)
    assert f["findings"]["shortfall_to_buffer"] == 0
    assert payout_hold_sentence(f["findings"]) == ""
    for a in generate_alerts(lina, f, include_financing=False)["alerts"]:
        assert "underlying cause" not in a["detail"]


def test_partial_cover_is_stated_as_a_share():
    from app.tools.alerts import payout_hold_sentence
    text = payout_hold_sentence({"shortfall_to_buffer": 10_000.0, "payout_hold": {
        "held_at_trough": 2_500.0, "trough_date": "2026-10-04", "share_of_gap_pct": 25.0,
        "covers_gap": False, "hold_days": 10, "cadence_days": 14}})
    assert "about 25% of the EUR 10,000 gap" in text


# ---------------------------------------------------------------------------
# B4 - the sales baseline is per calendar day, not per ledger row
# ---------------------------------------------------------------------------

def _resplit_sales(ctx: SellerContext, rows_per_day: int) -> SellerContext:
    """The same daily sales, recorded as several order rows per day."""
    txns = []
    for t in ctx.transactions:
        if t.type != "sale":
            txns.append(t)
            continue
        for k in range(rows_per_day):
            txns.append(Transaction(f"{t.txn_id}-{k}", t.seller_id, t.date, t.ledger, t.type,
                                    t.category, t.amount / rows_per_day, t.counterparty, t.memo))
    out = SellerContext(profile=ctx.profile, transactions=txns, as_of=ctx.as_of)
    out.metrics = compute_metrics(out)
    return out


def test_per_order_rows_give_the_same_forecast_as_daily_rows(amara):
    """Before the fix, 4 order rows per day cut projected sales to a quarter."""
    daily = forecast_cashflow(amara, 60)
    per_order = forecast_cashflow(_resplit_sales(amara, 4), 60)
    for a, b in zip(daily["series"], per_order["series"]):
        assert b["projected_sales"] == pytest.approx(a["projected_sales"], abs=0.02), a["date"]
    assert per_order["findings"]["trough_balance"] == pytest.approx(
        daily["findings"]["trough_balance"], abs=1.0)


def test_a_day_with_no_sales_counts_as_zero(amara):
    from app.tools.forecast import _weekday_baseline
    before, _ = _weekday_baseline(amara)
    closed_day = config.AS_OF - timedelta(days=7)  # one day inside the 56-day window
    txns = [t for t in amara.transactions if not (t.type == "sale" and t.date == closed_day)]
    ctx = SellerContext(profile=amara.profile, transactions=txns, as_of=amara.as_of)
    ctx.metrics = compute_metrics(ctx)
    after, _ = _weekday_baseline(ctx)
    wd = closed_day.weekday()
    assert after[wd] < before[wd]  # 8 such weekdays in the window, one now zero
    assert all(after[k] == pytest.approx(before[k]) for k in range(7) if k != wd)


def test_short_history_does_not_count_days_before_the_first_sale():
    from app.tools.forecast import _weekday_baseline
    ctx = get_seller("amara-prints", as_of=date(2026, 3, 14))  # 14 days of history
    baseline, _ = _weekday_baseline(ctx)
    assert min(baseline.values()) > 100


# ---------------------------------------------------------------------------
# LLM mode - the model must always be able to see the forecast's findings
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("horizon", [30, 60, 90, 180])
def test_findings_survive_the_cut_applied_to_tool_results_in_llm_mode(any_seller, horizon):
    """A tool result is cut to LLM_TOOL_RESULT_CHARS before the model sees it.
    Before this fix the findings of a 90- or 180-day forecast were cut off."""
    import json
    from app.tools.forecast import LLM_TOOL_RESULT_CHARS
    f = forecast_cashflow(any_seller, horizon)
    visible = json.dumps(f, default=str)[:LLM_TOOL_RESULT_CHARS]
    findings = json.dumps(f["findings"], default=str)
    assert findings in visible
