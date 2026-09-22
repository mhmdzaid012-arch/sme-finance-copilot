"""
What-if simulator.

Lets a seller change one or more assumptions and see the effect on the
projected bank balance, side by side with the baseline:

  * pay a scheduled bill later, or split it into two instalments
  * cut ad spend for a period (optionally assuming some lost sales)
  * a general rise or fall in sales
  * marketplace payouts arriving late - the forecaster's main sensitivity,
    so this doubles as a stress test the seller can run on themselves
  * a new monthly cost, such as hiring someone
  * taking a specific financing product, with its real arrival date and its
    real repayment schedule

Two honesty rules are built in:

1. **Money cannot arrive faster than the product can be arranged.** A
   facility is drawn on `as_of + speed_days`, so a slow product visibly fails
   to cover an early shortfall instead of appearing to fix it.
2. **Assumptions are stated, not hidden.** Cutting ads does not reduce sales
   unless the seller says so, and the reply says that plainly - the simulator
   does not pretend to know the seller's ad elasticity.

This is a T1 (recommend) tool: it changes nothing, it only projects.
"""

from __future__ import annotations

from datetime import timedelta

from ..store import SellerContext, load_financing_catalog
from .financing import RESTRICTED_USE_STRUCTURES, _amortised_total_cost, match_financing
from .forecast import Scenario, forecast_cashflow

LIMITS = {
    "delay_days": (0, 90),
    "ads_cut_pct": (0, 100),
    "ads_cut_days": (0, 90),
    "ads_sales_impact_pct": (0, 100),
    "sales_change_pct": (-50, 50),
    "payout_delay_days": (0, 21),
    "extra_monthly_cost": (0, 100000),
}


class WhatIfError(ValueError):
    """A scenario that cannot be simulated honestly (unknown bill, ineligible product...)."""


VERDICTS = {
    # One vocabulary, used everywhere, judged against the same safety buffer
    # the financing matcher uses - so the two tools can never disagree.
    "fixes": "Stays above the safety buffer throughout.",
    "avoids_negative": "Never goes negative, but still dips below the safety buffer.",
    "improves": "Still goes negative, but less severely.",
    "no_effect": "Makes no material difference to the low point.",
    "worsens": "Makes the low point worse.",
    "breaks": "Pushes a healthy position into the red.",
}
VERDICT_RANK = {"fixes": 0, "avoids_negative": 1, "improves": 2,
                "no_effect": 3, "worsens": 4, "breaks": 5}


def classify(bf: dict, sf: dict, buffer_level: float) -> tuple[str, str]:
    delta = sf["trough_balance"] - bf["trough_balance"]
    buf = _eur(buffer_level)
    if not bf["goes_negative"] and sf["goes_negative"]:
        return "breaks", f"This would push you into the red on {sf['first_negative_date']}."
    if abs(delta) < 1.0:
        return "no_effect", "This makes no real difference to your lowest point."
    if sf["days_below_buffer"] == 0:
        return "fixes", f"You stay above your {buf} safety buffer the whole time."
    if not sf["goes_negative"]:
        return "avoids_negative", (
            f"You never go negative, but you dip below your {buf} safety buffer "
            f"for {sf['days_below_buffer']} day(s).")
    if delta > 0:
        return "improves", f"Better, but you still go negative from {sf['first_negative_date']}."
    return "worsens", "This makes the shortfall worse."


def verify_financing_options(ctx: SellerContext, options: list[dict], amount: float,
                             days_needed: int, horizon_days: int = 120) -> list[dict]:
    """
    Simulate each candidate product end to end - arrival date and repayments
    included - before anything is recommended. A product that is cheap on
    paper but whose repayments open a new hole next month is caught here.
    """
    out = []
    for e in options:
        try:
            r = simulate(ctx, {"horizon_days": horizon_days, "financing": {
                "product_id": e["id"], "amount": amount, "days_needed": days_needed}})
        except WhatIfError:
            continue
        sf = r["scenario"]["findings"]
        out.append({
            "id": e["id"], "name": e["name"], "speed_days": e["speed_days"],
            "verdict": r["verdict"], "verdict_text": r["summary_lines"][0],
            "cost": r["financing"]["cost"],
            "trough_balance": sf["trough_balance"],
            "days_below_buffer": sf["days_below_buffer"],
            "goes_negative": sf["goes_negative"],
        })
    out.sort(key=lambda x: (VERDICT_RANK[x["verdict"]], x["cost"]))
    return out


def _clamp(name: str, value) -> float:
    lo, hi = LIMITS[name]
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise WhatIfError(f"'{name}' must be a number.")
    return max(lo, min(hi, v))


def _eur(x: float) -> str:
    return ("-" if x < 0 else "") + f"EUR {abs(x):,.0f}"


def whatif_options(ctx: SellerContext) -> dict:
    """Everything the UI needs to offer sensible choices for this seller."""
    base = forecast_cashflow(ctx, 60)
    fi = base["findings"]
    amount = fi["suggested_bridge_amount"] or round(ctx.metrics["avg_monthly_revenue"] * 0.3, -2)
    match = match_financing(ctx, amount, "working_capital",
                            fi["suggested_bridge_days"] or 30,
                            fi["days_until_first_shortfall"])
    return {
        "seller_id": ctx.seller_id,
        "obligations": [
            {"counterparty": o["counterparty"], "amount": o["amount"], "due": o["due"]}
            for o in ctx.profile.get("scheduled_obligations", [])
        ],
        "financing_products": [
            {"id": e["id"], "name": e["name"], "speed_days": e["speed_days"],
             "too_slow": e["too_slow"], "cost_for_period": e["cost"]["cost_for_period"]}
            for e in match["eligible"]
        ],
        "suggested_amount": amount,
        "suggested_days": fi["suggested_bridge_days"] or 30,
        "limits": LIMITS,
    }


def _financing_events(ctx: SellerContext, product: dict, amount: float,
                      days_needed: int) -> tuple[list[dict], dict | None, dict]:
    """
    Translate a product into dated cash movements. Returns
    (extra_events, revenue_share_config, description).
    """
    terms = product["terms"]
    cm = terms["cost_model"]
    draw = ctx.as_of + timedelta(days=int(terms["speed_days"]))
    events = [{"date": draw, "amount": amount, "counterparty": product["name"],
               "category": "financing_drawdown"}]
    rs = None
    kind = cm["type"]
    structure = terms.get("structure")

    if kind == "factoring":
        fee = amount * cm["fee_pct_per_30d"] * (days_needed / 30.0)
        events.append({"date": draw + timedelta(days=days_needed), "amount": -(amount + fee),
                       "counterparty": f"{product['name']} repayment",
                       "category": "financing_repayment"})
        desc = (f"EUR {amount:,.0f} arrives on {draw.isoformat()} and is repaid with a "
                f"EUR {fee:,.0f} fee after {days_needed} days.")
        cost = fee
    elif kind == "revenue_share":
        total = amount * cm["factor_rate"]
        rs = {"start": draw, "share": cm["share_of_daily_sales"], "total": total,
              "counterparty": f"{product['name']} repayment"}
        desc = (f"EUR {amount:,.0f} arrives on {draw.isoformat()}; then "
                f"{cm['share_of_daily_sales'] * 100:.0f}% of every day's sales is taken "
                f"until EUR {total:,.0f} is repaid.")
        cost = total - amount
    elif structure == "revolving":
        interest = amount * cm["apr"] * (days_needed / 365.0)
        events.append({"date": draw + timedelta(days=days_needed), "amount": -(amount + interest),
                       "counterparty": f"{product['name']} repayment",
                       "category": "financing_repayment"})
        desc = (f"EUR {amount:,.0f} drawn on {draw.isoformat()} and cleared after "
                f"{days_needed} days with about EUR {interest:,.0f} interest.")
        cost = interest
    elif kind == "fixed_installment":
        term = int(cm["term_months"])
        total_interest = _amortised_total_cost(amount, cm["apr"], term)
        payment = (amount + total_interest) / term
        for k in range(1, term + 1):
            events.append({"date": draw + timedelta(days=30 * k), "amount": -payment,
                           "counterparty": f"{product['name']} instalment",
                           "category": "financing_repayment"})
        desc = (f"EUR {amount:,.0f} arrives on {draw.isoformat()}; then "
                f"{term} monthly instalments of about EUR {payment:,.0f}.")
        cost = total_interest
    else:
        raise WhatIfError(f"{product['name']} cannot be simulated as working capital.")

    return events, rs, {"text": desc, "arrives": draw.isoformat(), "cost": round(cost, 2)}


def simulate(ctx: SellerContext, params: dict) -> dict:
    """Run baseline and scenario side by side and explain the difference."""
    horizon = int(params.get("horizon_days", 60) or 60)
    sc = Scenario()
    changes: list[str] = []
    assumptions: list[str] = []
    financing_info = None

    obligations = {o["counterparty"]: o for o in ctx.profile.get("scheduled_obligations", [])}

    delay = params.get("delay_obligation")
    if delay:
        name = delay.get("counterparty")
        if name not in obligations:
            raise WhatIfError(f"No scheduled bill from '{name}' on file.")
        days = int(_clamp("delay_days", delay.get("days", 0)))
        if days:
            sc.obligation_shifts[name] = days
            changes.append(f"Pay {name} ({_eur(obligations[name]['amount'])}) {days} days later")
            assumptions.append(
                f"Assumes {name} agrees to the new date. Nothing here asks them - "
                f"that conversation is yours to have.")

    split = params.get("split_obligation")
    if split:
        if split not in obligations:
            raise WhatIfError(f"No scheduled bill from '{split}' on file.")
        sc.obligation_splits.add(split)
        changes.append(f"Split the {split} bill into two halves, 30 days apart")
        assumptions.append(f"Assumes {split} accepts two instalments.")

    ads_cut = _clamp("ads_cut_pct", params.get("ads_cut_pct", 0)) / 100.0
    if ads_cut > 0:
        sc.ads_cut_pct = ads_cut
        sc.ads_cut_days = int(_clamp("ads_cut_days", params.get("ads_cut_days", 30)))
        sc.ads_sales_impact_pct = _clamp(
            "ads_sales_impact_pct", params.get("ads_sales_impact_pct", 0)) / 100.0
        changes.append(f"Cut ad spend by {ads_cut * 100:.0f}% for {sc.ads_cut_days} days")
        if sc.ads_sales_impact_pct == 0:
            assumptions.append(
                "Assumes cutting ads loses no sales. That is optimistic: set an expected "
                "sales drop to see the trade-off honestly.")
        else:
            assumptions.append(
                f"Assumes sales fall {sc.ads_sales_impact_pct * 100:.0f}% while ads are cut "
                f"(your estimate, not a measured figure).")

    sales_change = _clamp("sales_change_pct", params.get("sales_change_pct", 0)) / 100.0
    if sales_change:
        sc.sales_change_pct = sales_change
        changes.append(f"Sales {'rise' if sales_change > 0 else 'fall'} "
                       f"{abs(sales_change) * 100:.0f}% across the whole period")

    payout_delay = int(_clamp("payout_delay_days", params.get("payout_delay_days", 0)))
    if payout_delay:
        sc.payout_delay_days = payout_delay
        changes.append(f"Every marketplace payout arrives {payout_delay} days late")

    extra = _clamp("extra_monthly_cost", params.get("extra_monthly_cost", 0))
    if extra:
        sc.extra_monthly_cost = extra
        changes.append(f"New monthly cost of {_eur(extra)}, charged on the 1st")

    fin = params.get("financing")
    if fin:
        products = {p["id"]: p for p in load_financing_catalog()["products"]}
        product = products.get(fin.get("product_id"))
        if product is None:
            raise WhatIfError("Unknown financing product.")
        if (product["type"] in RESTRICTED_USE_STRUCTURES
                or product["terms"].get("use_of_funds_restricted")):
            raise WhatIfError(
                f"{product['name']} cannot be used as working capital, so it cannot "
                f"cover this gap.")
        amount = float(fin.get("amount") or 0)
        if amount <= 0:
            raise WhatIfError("Financing amount must be positive.")
        days_needed = int(fin.get("days_needed") or 30)
        # Honesty rule: only simulate products the seller actually qualifies for.
        match = match_financing(ctx, amount, "working_capital", days_needed)
        entry = next((e for e in match["eligible"] if e["id"] == product["id"]), None)
        if entry is None:
            near = next((n for n in match["near_miss"] if n["id"] == product["id"]), None)
            reasons = ("; ".join(f"{w['label']}: needs {w['required']}, you have {w['actual']}"
                                 for w in near["why_not"]) if near else
                       "several eligibility criteria are not met")
            raise WhatIfError(f"You do not qualify for {product['name']} at "
                              f"EUR {amount:,.0f}: {reasons}.")
        events, rs, financing_info = _financing_events(ctx, product, amount, days_needed)
        sc.extra_events.extend(events)
        sc.revenue_share = rs
        changes.append(f"Take {product['name']}: {financing_info['text']}")
        assumptions.append(
            "Assumes the application is approved on the stated terms. Matching published "
            "criteria is not a credit decision.")

    if not changes:
        raise WhatIfError("Nothing to simulate - change at least one setting.")

    if sc.sales_change_pct < 0 or sc.ads_sales_impact_pct > 0:
        # Counter-intuitive but real: fewer orders means paying for fewer goods
        # and less shipping *now*, while the lost income only shows up later as
        # smaller payouts. The low point can briefly improve while the business
        # ends up poorer. Say so, so nobody reads the wrong line.
        assumptions.append(
            "Losing sales can briefly make the low point look better, because you pay "
            "for fewer orders straight away while the lost income only arrives later "
            "as smaller payouts. Judge this scenario on the ending balance, not just "
            "the low point.")

    base = forecast_cashflow(ctx, horizon)
    scen = forecast_cashflow(ctx, horizon, sc)
    bf, sf = base["findings"], scen["findings"]

    delta_trough = sf["trough_balance"] - bf["trough_balance"]
    end_base = base["series"][-1]["balance"]
    end_scen = scen["series"][-1]["balance"]

    verdict, headline = classify(bf, sf, base["safety_buffer"])

    lines = [
        headline,
        f"Lowest balance: {_eur(bf['trough_balance'])} ({bf['trough_date']}) becomes "
        f"{_eur(sf['trough_balance'])} ({sf['trough_date']}).",
        f"Days below your {_eur(base['safety_buffer'])} safety buffer: "
        f"{bf['days_below_buffer']} becomes {sf['days_below_buffer']}.",
        f"Balance at the end of the {horizon} days: {_eur(end_base)} becomes {_eur(end_scen)}.",
    ]
    if financing_info:
        lines.append(f"Financing cost in this scenario: about EUR {financing_info['cost']:,.0f}.")

    return {
        "seller_id": ctx.seller_id,
        "horizon_days": horizon,
        "changes": changes,
        "assumptions": assumptions,
        "verdict": verdict,
        "verdict_meaning": VERDICTS[verdict],
        "summary": " ".join(lines),
        "summary_lines": lines,
        "baseline": {
            "findings": bf,
            "series": [{"date": r["date"], "balance": r["balance"]} for r in base["series"]],
        },
        "scenario": {
            "findings": sf,
            "series": [{"date": r["date"], "balance": r["balance"]} for r in scen["series"]],
        },
        "comparison": {
            "trough_change": round(delta_trough, 2),
            "ending_balance_change": round(end_scen - end_base, 2),
            "days_below_buffer_change": sf["days_below_buffer"] - bf["days_below_buffer"],
            "negative_before": bf["goes_negative"],
            "negative_after": sf["goes_negative"],
        },
        "financing": financing_info,
        "safety_buffer": base["safety_buffer"],
        "disclaimer": (
            "A projection under the stated assumptions, on simulated data. It changes "
            "nothing and is not financial advice."
        ),
    }
