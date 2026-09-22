"""What-if simulator tests, including agreement with the financing matcher."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.store import get_seller
from app.tools.alerts import generate_alerts
from app.tools.financing import match_financing
from app.tools.forecast import Scenario, forecast_cashflow
from app.tools.whatif import (
    VERDICTS,
    WhatIfError,
    simulate,
    verify_financing_options,
    whatif_options,
)


def _series(f):
    return [(r["date"], r["balance"]) for r in f["series"]]


def test_empty_scenario_reproduces_the_baseline_exactly(any_seller):
    assert _series(forecast_cashflow(any_seller, 90)) == \
        _series(forecast_cashflow(any_seller, 90, Scenario()))


def test_delaying_a_bill_moves_the_payment_not_the_goods(amara):
    base = forecast_cashflow(amara, 90)
    moved = forecast_cashflow(amara, 90, Scenario(obligation_shifts={"Textil Nord GmbH": 30}))

    def paid_on(f):
        return [r["date"] for r in f["series"]
                if any(e["counterparty"] == "Textil Nord GmbH" for e in r["events"])]
    assert paid_on(base) == ["2026-09-25"]
    assert paid_on(moved) == ["2026-10-25"]
    # Paying later must not delay the stock: goods still arrive on the agreed date.
    first_stock = lambda f: next(r["date"] for r in f["series"] if r["cogs_covered_by_stock"] > 0)
    assert first_stock(base) == first_stock(moved) == "2026-09-25"


def test_split_pays_two_halves_thirty_days_apart(amara):
    f = forecast_cashflow(amara, 90, Scenario(obligation_splits={"Textil Nord GmbH"}))
    parts = [(r["date"], e["amount"]) for r in f["series"] for e in r["events"]
             if e["counterparty"] == "Textil Nord GmbH"]
    assert parts == [("2026-09-25", 3400.0), ("2026-10-25", 3400.0)]


def test_prebought_stock_is_not_paid_for_twice(amara):
    f = forecast_cashflow(amara, 120)
    # Amara's Q4 order is worth EUR 11,300 of stock (deposit + balance). All of
    # it should be drawn down against per-order product cost within the horizon.
    assert f["findings"]["stock_drawn_down"] == pytest.approx(11300.0, abs=1)
    assert f["findings"]["stock_remaining_at_horizon"] == pytest.approx(0.0, abs=1)


def test_late_payouts_make_things_worse(amara):
    r = simulate(amara, {"payout_delay_days": 5})
    assert r["comparison"]["trough_change"] < 0
    assert r["verdict"] in ("worsens", "breaks")


def test_cutting_ads_states_its_assumption(amara):
    r = simulate(amara, {"ads_cut_pct": 100, "ads_cut_days": 30})
    assert any("loses no sales" in a for a in r["assumptions"])
    with_loss = simulate(amara, {"ads_cut_pct": 100, "ads_cut_days": 30,
                                 "ads_sales_impact_pct": 20, "horizon_days": 90})
    no_loss = simulate(amara, {"ads_cut_pct": 100, "ads_cut_days": 30, "horizon_days": 90})
    # Lost sales make the business poorer by the end of the period...
    assert with_loss["scenario"]["series"][-1]["balance"] < \
        no_loss["scenario"]["series"][-1]["balance"]
    # ...even though the low point can briefly look better (fewer orders to pay
    # for now, smaller payouts later) - and the simulator must say so.
    assert any("ending balance" in a for a in with_loss["assumptions"])


def test_financing_arrives_only_after_it_can_be_arranged(amara):
    r = simulate(amara, {"financing": {"product_id": "ember-seasonal-bridge",
                                       "amount": 5000, "days_needed": 45}})
    assert r["financing"]["arrives"] == (amara.as_of + timedelta(days=6)).isoformat()


def test_revenue_share_is_repaid_from_sales(amara):
    sc_params = {"horizon_days": 180, "financing": {
        "product_id": "nordcap-rev-advance", "amount": 5000, "days_needed": 45}}
    r = simulate(amara, sc_params)
    assert r["financing"]["cost"] == pytest.approx(5000 * 0.09, abs=1)


@pytest.mark.parametrize("params,fragment", [
    ({"delay_obligation": {"counterparty": "Nobody Ltd", "days": 5}}, "No scheduled bill"),
    ({"financing": {"product_id": "craft-digital-grant", "amount": 3000}}, "working capital"),
    ({"financing": {"product_id": "atlas-term-loan", "amount": 30000}}, "do not qualify"),
    ({"financing": {"product_id": "nope", "amount": 3000}}, "Unknown financing"),
    ({}, "Nothing to simulate"),
])
def test_dishonest_scenarios_are_refused(amara, params, fragment):
    with pytest.raises(WhatIfError) as exc:
        simulate(amara, params)
    assert fragment in str(exc.value)


def test_verdicts_use_one_vocabulary(amara):
    for params in ({"payout_delay_days": 3}, {"split_obligation": "Textil Nord GmbH"},
                   {"extra_monthly_cost": 900}, {"sales_change_pct": 10}):
        r = simulate(amara, params)
        assert r["verdict"] in VERDICTS
        assert r["verdict_meaning"] == VERDICTS[r["verdict"]]


def test_matcher_and_simulator_agree_on_timing(amara):
    """
    Consistency between the two tools: a product the matcher flags as too slow
    lands after the balance has already dropped below the safety buffer, so
    the simulator must never claim it keeps the seller above the buffer.
    """
    fi = forecast_cashflow(amara, 60)["findings"]
    m = match_financing(amara, fi["suggested_bridge_amount"], "working_capital",
                        fi["suggested_bridge_days"], fi["days_until_first_shortfall"])
    slow = [e for e in m["eligible"] if e["too_slow"]]
    assert slow
    for v in verify_financing_options(amara, slow, fi["suggested_bridge_amount"],
                                      fi["suggested_bridge_days"]):
        assert v["verdict"] != "fixes", v["name"]
        assert v["days_below_buffer"] > 0


def test_recommended_financing_survives_simulation(amara, techfix):
    """Nothing is recommended unless its real repayments keep the seller out of the red."""
    for ctx in (amara, techfix):
        alerts = generate_alerts(ctx, forecast_cashflow(ctx, 60))
        for m in alerts["mitigations"]:
            if m["type"] == "financing" and m.get("product_id"):
                assert m["verified_verdict"] in ("fixes", "avoids_negative")


def test_an_expensive_fast_option_that_does_not_solve_it_is_not_recommended(amara):
    alerts = generate_alerts(amara, forecast_cashflow(amara, 60))
    recommended = {m.get("product_id") for m in alerts["mitigations"]}
    assert "swiftcash-mca" not in recommended


def test_options_endpoint_shapes(amara):
    o = whatif_options(amara)
    assert {b["counterparty"] for b in o["obligations"]} >= {"Textil Nord GmbH"}
    assert o["financing_products"]
    assert o["suggested_amount"] > 0


def test_healthy_seller_can_be_broken_by_a_bad_decision(lina):
    """The simulator must be able to say 'this would push you into the red'."""
    r = simulate(lina, {"extra_monthly_cost": 3000})
    assert r["verdict"] == "breaks"
