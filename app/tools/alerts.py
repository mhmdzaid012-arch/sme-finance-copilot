"""
Proactive cash-flow alerts.

An alert that only says "you will run out of money" is close to useless. Each
alert here carries three things:

  * the date and the amount, so it is checkable
  * the specific payments that caused it, so it is explicable
  * ranked mitigations with their real cost, so it is actionable

Mitigations are ordered cheapest-first among the options that can actually be
arranged in the available lead time. The free levers (asking for an early
payout, deferring discretionary ad spend, renegotiating a supplier date) are
deliberately offered before any borrowing, because the cheapest financing is
usually none.
"""

from __future__ import annotations

from datetime import date

from ..store import SellerContext
from .financing import match_financing
from .whatif import WhatIfError, simulate, verify_financing_options


def _tested(ctx: SellerContext, params: dict, horizon: int) -> str | None:
    """Run a what-if and return its one-line verdict, so an alert states a
    simulated result rather than a claim."""
    try:
        return simulate(ctx, dict(params, horizon_days=horizon))["summary_lines"][0]
    except WhatIfError:
        return None

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _fmt_eur(x: float) -> str:
    return f"EUR {x:,.0f}"


def generate_alerts(ctx: SellerContext, forecast: dict,
                    include_financing: bool = True) -> dict:
    """Turn a forecast into a ranked, actionable alert list."""
    f = forecast["findings"]
    m = ctx.metrics
    buffer_level = forecast["safety_buffer"]
    alerts: list[dict] = []

    trough_balance = f["trough_balance"]
    trough_date = f["trough_date"]
    lead_days = f["days_until_first_shortfall"]
    duration = f["suggested_bridge_days"] or None
    gap = f["shortfall_to_buffer"] or 0.0

    drivers = f["primary_drivers"]
    driver_text = ", ".join(
        f"{d['counterparty']} ({_fmt_eur(d['amount'])})" for d in drivers[:3]
    ) or "ordinary operating costs"

    # --- the headline cash alert ------------------------------------------
    if f["goes_negative"]:
        first_neg = f["first_negative_date"]
        alerts.append({
            "id": "cash_shortfall_critical",
            "severity": "critical",
            "date": first_neg,
            "headline": (
                f"Projected to run out of cash on {first_neg}"
            ),
            "detail": (
                f"On current trends the bank balance goes negative on {first_neg} and "
                f"bottoms out at {_fmt_eur(trough_balance)} on {trough_date}. The "
                f"payments driving it are {driver_text}. To stay above your "
                f"{_fmt_eur(buffer_level)} safety buffer throughout you would need "
                f"about {_fmt_eur(gap)} for roughly {duration} days."
            ),
            "amount_needed": round(gap, 2),
            "days_needed": duration,
            "lead_time_days": lead_days,
        })
    elif f["days_below_buffer"] > 0:
        alerts.append({
            "id": "cash_below_buffer",
            "severity": "warning",
            "date": f["first_below_buffer_date"],
            "headline": (
                f"Cash dips below your safety buffer on {f['first_below_buffer_date']}"
            ),
            "detail": (
                f"The balance stays under your {_fmt_eur(buffer_level)} buffer for "
                f"{f['days_below_buffer']} day(s), reaching a low of "
                f"{_fmt_eur(trough_balance)} on {trough_date}. It does not go negative, "
                f"so this is a thin-margin warning rather than a missed-payment risk. "
                f"Main drivers: {driver_text}."
            ),
            "amount_needed": round(gap, 2),
            "days_needed": duration,
            "lead_time_days": lead_days,
        })
    else:
        alerts.append({
            "id": "cash_healthy",
            "severity": "info",
            "date": trough_date,
            "headline": (
                f"No cash shortfall projected in the next "
                f"{forecast['horizon_days']} days"
            ),
            "detail": (
                f"The tightest point is {_fmt_eur(trough_balance)} on {trough_date}, "
                f"which stays above your {_fmt_eur(buffer_level)} buffer. Nothing to "
                f"act on right now."
            ),
            "amount_needed": 0.0,
            "days_needed": None,
            "lead_time_days": None,
        })

    # --- concentration risk: one payment dominating the trough ------------
    if drivers and gap > 0:
        top = drivers[0]
        if top["amount"] >= gap * 0.6:
            alerts.append({
                "id": "single_payment_concentration",
                "severity": "warning",
                "date": trough_date,
                "headline": (
                    f"One payment causes most of the squeeze: "
                    f"{top['counterparty']} at {_fmt_eur(top['amount'])}"
                ),
                "detail": (
                    f"This single obligation is the biggest cause of the "
                    f"{_fmt_eur(gap)} gap."
                    + (lambda t30, tsplit: (
                        f" Tested: paying it 30 days later - {t30.lower()}"
                        if t30 else "")
                       + (f" Splitting it into two instalments - {tsplit.lower()}"
                          if tsplit else ""))(
                        _tested(ctx, {"delay_obligation": {"counterparty": top["counterparty"], "days": 30}},
                                forecast["horizon_days"])
                        if any(o["counterparty"] == top["counterparty"]
                               for o in ctx.profile.get("scheduled_obligations", [])) else None,
                        _tested(ctx, {"split_obligation": top["counterparty"]}, forecast["horizon_days"])
                        if any(o["counterparty"] == top["counterparty"]
                               for o in ctx.profile.get("scheduled_obligations", [])) else None)
                ),
                "amount_needed": round(top["amount"], 2),
                "days_needed": duration,
                "lead_time_days": lead_days,
            })

    # --- structural warning: trapped cash ---------------------------------
    daily_sales = m["avg_monthly_revenue"] / 30.0
    trapped_days = (m["platform_balance"] / daily_sales) if daily_sales > 0 else 0.0
    if trapped_days >= 10 and gap > 0:
        alerts.append({
            "id": "payout_hold_structural",
            "severity": "info",
            "date": forecast["as_of"],
            "headline": (
                f"{_fmt_eur(m['platform_balance'])} of your own money is stuck in the "
                f"payout queue"
            ),
            "detail": (
                f"That is about {trapped_days:.0f} days of sales you have earned but "
                f"cannot spend, because payouts run every "
                f"{ctx.profile['payout_schedule']['cadence_days']} days after a "
                f"{ctx.profile['payout_schedule']['hold_days']}-day hold. This is the "
                f"root cause rather than a one-off: any facility secured against the "
                f"payout queue treats the timing problem directly, and a shorter hold "
                f"or more frequent payouts would reduce the need for financing at all."
            ),
            "amount_needed": 0.0,
            "days_needed": None,
            "lead_time_days": None,
        })

    # --- mitigations -------------------------------------------------------
    mitigations: list[dict] = []
    if gap > 0:
        # 1. Free levers first.
        # Bringing a payout forward only helps if it would otherwise land AFTER
        # the balance first dips below the buffer. A payout that already lands
        # before the dip is counted in the forecast, so asking for it earlier
        # changes nothing - offering it would be advice that cannot work.
        first_dip = f["first_below_buffer_date"]
        next_payout = next(
            (p for p in forecast["payout_events"] if first_dip and p["date"] > first_dip),
            None,
        )
        if next_payout:
            buffer = forecast["safety_buffer"]
            before = [d for d in forecast["series"]
                      if first_dip <= d["date"] < next_payout["date"]]
            early_deficit = max((buffer - d["balance"] for d in before), default=0.0)
            still_short_after = any(d["balance"] < buffer for d in forecast["series"]
                                    if d["date"] >= next_payout["date"])
            if next_payout["amount"] >= early_deficit:
                effect = (f"Received before {first_dip}, it covers the dip below your "
                          f"buffer until {next_payout['date']}")
            else:
                effect = (f"Received before {first_dip}, it covers "
                          f"{_fmt_eur(next_payout['amount'])} of the "
                          f"{_fmt_eur(early_deficit)} you are short before {next_payout['date']}")
            effect += (", but it does not close the later gap on its own, because that "
                       "payout is already counted in this forecast."
                       if still_short_after else ".")
            mitigations.append({
                "rank": 1,
                "type": "free",
                "action": "Request an early or expedited payout",
                "detail": (
                    f"Your next payout after the squeeze starts is "
                    f"{_fmt_eur(next_payout['amount'])} on {next_payout['date']}. Most "
                    f"marketplaces will bring a payout forward on request, sometimes for "
                    f"a small flat fee. {effect} It is the cheapest lever because it is "
                    f"your own money."
                ),
                "cost": 0.0,
                "payout_date": next_payout["date"],
                "covers_whole_gap": not still_short_after
                and next_payout["amount"] >= early_deficit,
            })

        ads_90 = m["expense_breakdown_90d"].get("advertising", 0.0)
        if ads_90 > 0 and duration:
            ads_saving = ads_90 / 90.0 * min(duration, 30)
            if ads_saving > gap * 0.1:
                mitigations.append({
                    "rank": 2,
                    "type": "free",
                    "action": "Pause or reduce discretionary ad spend",
                    "detail": (
                        f"Ads are running at about "
                        f"{_fmt_eur(ads_90 / 90.0)}/day. Pausing for "
                        f"{min(duration, 30)} days frees roughly "
                        f"{_fmt_eur(ads_saving)} - it will cost you some sales, but it "
                        f"is reversible within a day and needs nobody's approval."
                    ),
                    "cost": 0.0,
                })

        big_obligations = [
            o for o in forecast["scheduled_obligations"] if o["amount"] >= gap * 0.4
        ]
        for o in big_obligations[:1]:
            mitigations.append({
                "rank": 3,
                "type": "free",
                "action": f"Ask {o['counterparty']} for extended terms",
                "detail": (
                    f"The {_fmt_eur(o['amount'])} payment due {o['date']} is the largest "
                    f"single item. Moving it 30 days, or splitting it in two, costs "
                    f"nothing but a conversation and may well be granted for an "
                    f"established account."
                    + (f" Context on file: {o['note']}." if o.get("note") else "")
                ),
                "cost": 0.0,
            })

        # 2. Then borrowing, cheapest option that can actually arrive in time.
        if include_financing:
            match = match_financing(
                ctx, amount=gap, purpose="working_capital",
                days_needed=duration, days_until_needed=lead_days,
            )
            in_time = [e for e in match["eligible"] if not e["too_slow"]]
            # Every candidate is simulated end to end - arrival date and
            # repayments included - before it is recommended. Cheap on paper is
            # not enough: the repayments must not open a new hole later.
            verified = verify_financing_options(ctx, in_time, gap, duration or 30)
            solves = [v for v in verified if v["verdict"] in ("fixes", "avoids_negative")]
            by_id = {e["id"]: e for e in in_time}
            for i, v in enumerate(solves[:2]):
                option = by_id[v["id"]]
                mitigations.append({
                    "rank": 4 + i,
                    "type": "financing",
                    "action": f"Finance the gap: {option['name']}",
                    "detail": (
                        f"{option['cost']['explanation']} Arranges in about "
                        f"{option['speed_days']} day(s). Simulated with its real "
                        f"repayments: {v['verdict_text']}"
                    ),
                    "cost": v["cost"],
                    "product_id": option["id"],
                    "verified_verdict": v["verdict"],
                })
            rejected = [v for v in verified if v["verdict"] not in ("fixes", "avoids_negative")]
            if in_time and not solves:
                mitigations.append({
                    "rank": 4,
                    "type": "financing",
                    "action": "No in-time financing fully solves this",
                    "detail": (
                        "Every product that can arrive in time was simulated with its real "
                        "repayments, and none keeps the balance out of the red. "
                        + (f"Closest: {rejected[0]['name']} - {rejected[0]['verdict_text']}"
                           if rejected else "")
                    ),
                    "cost": 0.0,
                })
            if not in_time and match["eligible"]:
                mitigations.append({
                    "rank": 4,
                    "type": "financing",
                    "action": "No financing can be arranged in time",
                    "detail": (
                        f"Every matching product takes longer than the {lead_days} days "
                        f"available. The free levers above are the realistic route this "
                        f"time; put a facility in place afterwards so the next peak is "
                        f"not a scramble."
                    ),
                    "cost": 0.0,
                })
            elif not match["eligible"]:
                mitigations.append({
                    "rank": 4,
                    "type": "financing",
                    "action": "No product in the catalog matches this requirement",
                    "detail": (
                        "On published eligibility criteria nothing fits. The near-miss "
                        "list shows exactly which tests failed and what would have to "
                        "change."
                    ),
                    "cost": 0.0,
                })

    alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a["severity"], 9), a["date"] or ""))
    mitigations.sort(key=lambda x: (x["rank"], x["cost"]))

    counts = {s: sum(1 for a in alerts if a["severity"] == s)
              for s in ("critical", "warning", "info")}

    return {
        "seller_id": ctx.seller_id,
        "as_of": forecast["as_of"],
        "horizon_days": forecast["horizon_days"],
        "alert_counts": counts,
        "highest_severity": alerts[0]["severity"] if alerts else "info",
        "alerts": alerts,
        "mitigations": mitigations,
        "disclaimer": (
            "Alerts are generated from a rule-based projection over simulated data. "
            "They are informational prompts, not instructions, and not financial advice."
        ),
    }
