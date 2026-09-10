"""Financing engine tests: cost maths, eligibility reasoning, ranking honesty."""

from __future__ import annotations

import pytest

from app.store import load_financing_catalog
from app.tools.financing import (
    _amortised_total_cost,
    _cost_of_capital,
    match_financing,
)


# ---------------------------------------------------------------------------
# Cost arithmetic
# ---------------------------------------------------------------------------

def test_amortisation_matches_closed_form():
    """
    EUR 10,000 at 12% nominal over 12 months. Level payment is
    P*r/(1-(1+r)^-n) = 888.49, so total interest is 661.85.
    """
    assert _amortised_total_cost(10000, 0.12, 12) == pytest.approx(661.85, abs=0.5)
    assert _amortised_total_cost(10000, 0.0, 12) == 0.0
    assert _amortised_total_cost(10000, 0.12, 0) == 0.0


def _product(pid: str) -> dict:
    return next(p for p in load_financing_catalog()["products"] if p["id"] == pid)


def test_factoring_cost_scales_with_days():
    p = _product("brightbridge-factoring")
    c30 = _cost_of_capital(p, 10000, 20000, days_needed=30)
    c60 = _cost_of_capital(p, 10000, 20000, days_needed=60)
    assert c60["cost_for_period"] == pytest.approx(c30["cost_for_period"] * 2, rel=0.01)
    # 2.4% per 30 days on 10k
    assert c30["cost_for_period"] == pytest.approx(240.0, abs=1)


def test_revenue_share_cost_is_fixed_regardless_of_period():
    """A factor rate cannot be reduced by repaying early - that is the trap."""
    p = _product("nordcap-rev-advance")
    c30 = _cost_of_capital(p, 10000, 20000, days_needed=30)
    c90 = _cost_of_capital(p, 10000, 20000, days_needed=90)
    assert c30["cost_for_period"] == c90["cost_for_period"]
    assert c30["cost_for_period"] == pytest.approx(900.0, abs=1)  # factor 1.09
    # Faster repayment means a *higher* effective APR, which must be surfaced.
    assert c30["effective_apr"] > 0.09


def test_committed_term_loan_is_not_priced_as_a_short_bridge():
    """
    A 36-month microloan must not appear cheaper than a 54-day facility just
    because a pro-rated slice of its interest is small. The comparable cost is
    the whole-term cost you actually commit to.
    """
    p = _product("eu-micro-starter")
    c = _cost_of_capital(p, 2000, 4000, days_needed=30)
    assert c["cost_for_period"] == c["total_cost"]
    assert c["term_exceeds_need"] is True
    # The early-repayment figure is still disclosed, but separately.
    assert c["if_repaid_early"] < c["total_cost"]


def test_revolving_facility_is_priced_per_day_drawn():
    p = _product("harbor-overdraft")
    c = _cost_of_capital(p, 10000, 30000, days_needed=10)
    assert c["structure"] == "revolving"
    # 16.4% APR on 10k for 10 days
    assert c["cost_for_period"] == pytest.approx(10000 * 0.164 * 10 / 365, rel=0.01)
    assert c["cost_for_period"] < c["total_cost"]


def test_early_repayment_never_costs_more_than_full_term():
    for pid in ("eu-micro-starter", "ember-seasonal-bridge", "hanse-inventory-finance",
                "verde-sustainability-loan", "lusitania-micro"):
        p = _product(pid)
        c = _cost_of_capital(p, 20000, 25000, days_needed=120)
        if c.get("if_repaid_early") is not None:
            assert c["if_repaid_early"] <= c["total_cost"] + 0.01, pid


def test_grant_has_no_cost_but_discloses_co_funding():
    p = _product("craft-digital-grant")
    c = _cost_of_capital(p, 4000, 6000)
    assert c["cost_for_period"] == 0.0
    assert c["own_contribution_required"] == pytest.approx(1000.0)  # 25%


# ---------------------------------------------------------------------------
# Eligibility reasoning
# ---------------------------------------------------------------------------

def test_every_check_is_a_complete_checkable_statement(amara):
    r = match_financing(amara, 9000, days_needed=54, days_until_needed=7)
    for entry in r["eligible"] + r["near_miss"]:
        assert entry["checks"], entry["id"]
        for c in entry["checks"]:
            assert set(("criterion", "label", "required", "actual", "passed")) <= set(c)
            assert c["required"] not in (None, "")
            assert c["actual"] not in (None, "")


def test_eligible_products_have_no_failed_criteria(any_seller):
    r = match_financing(any_seller, 8000)
    for e in r["eligible"]:
        assert e["failed_criteria"] == []
        assert all(c["passed"] for c in e["checks"])


def test_near_miss_explains_the_gap_and_the_remedy(techfix):
    """TechFix is blocked by leverage; the engine must say so and quantify it."""
    r = match_financing(techfix, 20000, days_needed=54, days_until_needed=7)
    nordcap = next((n for n in r["near_miss"] if n["id"] == "nordcap-rev-advance"), None)
    assert nordcap is not None
    reasons = {w["label"] for w in nordcap["why_not"]}
    assert any("debt" in x.lower() for x in reasons)
    hint = next(w["hint"] for w in nordcap["why_not"] if "debt" in w["label"].lower())
    assert "pay" in hint.lower() and "EUR" in hint


def test_young_high_refund_seller_is_honestly_rejected(lina):
    """
    Lina has 8 months of trading and a ~8% refund rate. The premium products
    must be refused, and the refusal must name the failing test.
    """
    r = match_financing(lina, 5000)
    eligible_ids = {e["id"] for e in r["eligible"]}
    assert "helios-rev-advance-plus" not in eligible_ids
    assert "atlas-term-loan" not in eligible_ids
    assert "meridian-credit-line" not in eligible_ids

    all_entries = {e["id"]: e for e in r["eligible"] + r["near_miss"]}
    if "nordcap-rev-advance" in all_entries:
        failed = all_entries["nordcap-rev-advance"]["failed_criteria"]
        assert "min_months_trading" in failed or "max_refund_rate" in failed


def test_microfinance_is_bounded_to_micro_enterprises(techfix):
    """A EUR 40k/month business must not be matched to a starter microloan."""
    r = match_financing(techfix, 20000)
    assert "eu-micro-starter" not in {e["id"] for e in r["eligible"]}


def test_country_restriction_is_enforced(amara, lina):
    """Lusitania Micro is PT/ES only."""
    assert "lusitania-micro" not in {e["id"] for e in match_financing(amara, 5000)["eligible"]}
    assert "lusitania-micro" in {e["id"] for e in match_financing(lina, 5000)["eligible"]}


def test_category_exclusion_is_enforced(lina):
    """Hanse inventory finance excludes handmade homeware."""
    r = match_financing(lina, 8000)
    assert "hanse-inventory-finance" not in {e["id"] for e in r["eligible"]}


# ---------------------------------------------------------------------------
# Ranking and purpose
# ---------------------------------------------------------------------------

def test_ranking_is_by_cost_for_period_among_options_that_arrive_in_time(amara):
    r = match_financing(amara, 9000, days_needed=54, days_until_needed=7)
    in_time = [e for e in r["eligible"] if not e["too_slow"]]
    costs = [e["cost"]["cost_for_period"] for e in in_time]
    assert costs == sorted(costs)
    # Anything too slow is sorted after everything that is not.
    flags = [e["too_slow"] for e in r["eligible"]]
    assert flags == sorted(flags)


def test_products_that_cannot_arrive_in_time_are_flagged_not_recommended(amara):
    r = match_financing(amara, 9000, days_needed=54, days_until_needed=7)
    slow = [e for e in r["eligible"] if e["too_slow"]]
    assert slow, "expected at least one product slower than the 7-day lead time"
    for e in slow:
        assert e["speed_days"] > 7
        assert "timing_warning" in e
    assert not r["summary"].startswith("No product")


def test_lead_time_and_duration_are_independent(lina):
    """
    Needing money for a long time is not the same as having a long time to
    arrange it. With generous lead time, a slow product is not penalised.
    """
    slow_lead = match_financing(lina, 3000, days_needed=90, days_until_needed=60)
    tight_lead = match_financing(lina, 3000, days_needed=90, days_until_needed=2)
    slow_ok = {e["id"] for e in slow_lead["eligible"] if not e["too_slow"]}
    tight_ok = {e["id"] for e in tight_lead["eligible"] if not e["too_slow"]}
    assert tight_ok < slow_ok


def test_restricted_use_funds_are_excluded_from_working_capital(any_seller):
    r = match_financing(any_seller, 6000, purpose="working_capital")
    for e in r["eligible"]:
        assert not e["use_restricted"], e["id"]
    for w in r["excluded_wrong_purpose"]:
        assert "excluded_reason" in w


def test_expensive_fast_option_is_offered_but_priced_honestly(amara):
    """
    A merchant cash advance is kept in the catalog on purpose. It must appear
    when eligible, and its cost must be shown as dramatically worse.
    """
    r = match_financing(amara, 9000, days_needed=54, days_until_needed=7)
    mca = next((e for e in r["eligible"] if e["id"] == "swiftcash-mca"), None)
    assert mca is not None
    cheapest = min(e["cost"]["cost_for_period"] for e in r["eligible"])
    assert mca["cost"]["cost_for_period"] > cheapest * 3
    assert mca["cost"]["effective_apr"] > 0.5


def test_amount_defaults_to_something_sane(amara):
    r = match_financing(amara)
    assert r["requested_amount"] > 0
    assert r["requested_amount"] <= amara.metrics["avg_monthly_revenue"]


def test_output_always_carries_the_not_underwriting_disclaimer(any_seller):
    r = match_financing(any_seller, 5000)
    assert "not underwriting" in r["disclaimer"].lower()
    assert "illustrative" in r["catalog_disclaimer"].lower()
