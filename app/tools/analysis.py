"""
Business financial analysis in plain English.

The job here is translation, not calculation. A micro-seller does not need
another dashboard of ratios; they need to be told which two numbers in their
business are actually worth their attention this month, and why.

Every observation carries the figure it came from, so the seller can check it.
Benchmarks are explicitly synthetic and labelled as such wherever they surface.
"""

from __future__ import annotations

import json
from datetime import timedelta
from functools import lru_cache

from .. import config
from ..store import SellerContext, detect_recurring


@lru_cache(maxsize=1)
def _benchmarks() -> dict:
    return json.loads((config.DATA_DIR / "benchmarks.json").read_text(encoding="utf-8"))


def _percentile_position(value: float, band: dict, lower_is_better: bool = False) -> dict:
    """Locate a value in a p25/median/p75 band and say what it means."""
    p25, med, p75 = band["p25"], band["median"], band["p75"]
    if value < p25:
        pos = "bottom quartile" if not lower_is_better else "top quartile"
    elif value < med:
        pos = "below median" if not lower_is_better else "above median"
    elif value < p75:
        pos = "above median" if not lower_is_better else "below median"
    else:
        pos = "top quartile" if not lower_is_better else "bottom quartile"

    if lower_is_better:
        favourable = value <= med
    else:
        favourable = value >= med

    return {
        "value": round(value, 4),
        "p25": p25,
        "median": med,
        "p75": p75,
        "position": pos,
        "favourable": favourable,
    }


def _month_revenue(ctx: SellerContext, months_back: int) -> float:
    """Gross sales over a trailing 30-day block, `months_back` blocks ago."""
    end = ctx.as_of - timedelta(days=30 * months_back)
    start = end - timedelta(days=29)
    return sum(
        t.amount for t in ctx.transactions
        if t.type == "sale" and start <= t.date <= end
    )


def analyse_business(ctx: SellerContext) -> dict:
    m = ctx.metrics
    p = ctx.profile
    bench_all = _benchmarks()
    bench = bench_all["categories"].get(p["category"])

    rev_now = _month_revenue(ctx, 0)
    rev_prev = _month_revenue(ctx, 1)
    rev_prev2 = _month_revenue(ctx, 2)
    mom = ((rev_now / rev_prev - 1) if rev_prev > 0 else 0.0)
    mom_prev = ((rev_prev / rev_prev2 - 1) if rev_prev2 > 0 else 0.0)

    # Contribution margin: what each euro of sales leaves after the costs that
    # scale with sales. This is the number that decides whether growth helps.
    w = ctx.window(config.SALES_BASELINE_WINDOW_DAYS)
    sales_w = sum(t.amount for t in w if t.type == "sale") or 1e-9
    variable = sum(
        abs(t.amount) for t in w
        if t.amount < 0 and t.category in {"cogs", "shipping", "advertising"}
    )
    fees = abs(sum(t.amount for t in w if t.type in {"platform_fee", "refund"}))
    contribution_margin = 1.0 - (variable + fees) / sales_w

    fixed_monthly = sum(
        r["amount"] * (30.0 / max(r["cadence_days"], 1))
        for r in detect_recurring(ctx)
    )
    monthly_contribution = m["avg_monthly_revenue"] * contribution_margin
    est_monthly_net = monthly_contribution - fixed_monthly
    breakeven_revenue = (fixed_monthly / contribution_margin) if contribution_margin > 0 else None

    # Cash trapped in the payout queue, expressed as days of sales. This is the
    # defining constraint of the niche and rarely shown to sellers anywhere.
    daily_sales = m["avg_monthly_revenue"] / 30.0
    trapped_days = (m["platform_balance"] / daily_sales) if daily_sales > 0 else 0.0

    expenses = m["expense_breakdown_90d"]
    total_expenses = sum(expenses.values()) or 1e-9
    top_expenses = [
        {
            "category": cat,
            "amount_90d": amt,
            "pct_of_expenses": round(amt / total_expenses, 4),
            "pct_of_revenue": round(amt / m["revenue_90d"], 4) if m["revenue_90d"] else 0.0,
        }
        for cat, amt in list(expenses.items())[:6]
    ]

    comparisons: dict[str, dict] = {}
    if bench:
        comparisons = {
            "gross_margin": _percentile_position(m["gross_margin"], bench["gross_margin"]),
            "refund_rate": _percentile_position(m["refund_rate"], bench["refund_rate"], True),
            "platform_fee_rate": _percentile_position(
                m["platform_fee_rate"], bench["platform_fee_rate"], True),
        }
        if m["cash_buffer_days"] is not None:
            comparisons["cash_buffer_days"] = _percentile_position(
                m["cash_buffer_days"], bench["cash_buffer_days"])

    # --- observations, ordered by what would change a decision -------------
    observations: list[dict] = []

    if est_monthly_net > 0:
        observations.append({
            "severity": "good",
            "headline": f"The business makes about EUR {est_monthly_net:,.0f} a month",
            "detail": (
                f"Every EUR 100 of sales leaves EUR {contribution_margin * 100:.0f} after "
                f"product, shipping, ads, platform fees and refunds. That covers "
                f"EUR {fixed_monthly:,.0f} of monthly fixed costs and leaves about "
                f"EUR {est_monthly_net:,.0f}. Break-even is around "
                f"EUR {breakeven_revenue:,.0f} of monthly sales."
            ),
        })
    else:
        observations.append({
            "severity": "critical",
            "headline": f"The business is losing about EUR {abs(est_monthly_net):,.0f} a month",
            "detail": (
                f"Contribution margin of {contribution_margin * 100:.0f}% on "
                f"EUR {m['avg_monthly_revenue']:,.0f} of sales generates "
                f"EUR {monthly_contribution:,.0f}, which does not cover "
                f"EUR {fixed_monthly:,.0f} of fixed costs. Financing would postpone "
                f"this, not fix it: sales need to reach about "
                f"EUR {breakeven_revenue:,.0f}/month, or fixed costs have to fall."
            ),
        })

    if trapped_days >= 5:
        observations.append({
            "severity": "warning" if trapped_days >= 10 else "info",
            "headline": (
                f"EUR {m['platform_balance']:,.0f} is earned but not yet in the bank"
            ),
            "detail": (
                f"That is about {trapped_days:.0f} days of sales sitting in the payout "
                f"queue, released every {p['payout_schedule']['cadence_days']} days after "
                f"a {p['payout_schedule']['hold_days']}-day hold. It is real money you "
                f"cannot spend, and it is the main reason a profitable month can still "
                f"leave you short."
            ),
        })

    if bench and comparisons.get("refund_rate") and not comparisons["refund_rate"]["favourable"]:
        r = comparisons["refund_rate"]
        observations.append({
            "severity": "warning",
            "headline": f"Refund rate of {m['refund_rate'] * 100:.1f}% is high for the category",
            "detail": (
                f"Peer median is {r['median'] * 100:.1f}% and the upper quartile starts at "
                f"{r['p75'] * 100:.1f}%, putting you in the {r['position']}. Refunds cost "
                f"you twice - lost revenue and the shipping already spent - and several "
                f"lenders cap refund rate as an eligibility criterion, so this narrows "
                f"your financing options as well as your margin."
            ),
        })

    ads = next((e for e in top_expenses if e["category"] == "advertising"), None)
    if ads and bench and ads["pct_of_revenue"] > bench["ad_spend_pct_of_revenue"]["p75"]:
        observations.append({
            "severity": "info",
            "headline": (
                f"Ad spend is {ads['pct_of_revenue'] * 100:.0f}% of revenue, "
                f"above the category's upper quartile"
            ),
            "detail": (
                f"Peers in the upper quartile spend "
                f"{bench['ad_spend_pct_of_revenue']['p75'] * 100:.0f}%. Ads are also the "
                f"fastest lever you control: unlike rent or wages, it can be cut within "
                f"days if cash gets tight."
            ),
        })

    if m["cash_buffer_days"] is not None and m["cash_buffer_days"] < 14:
        observations.append({
            "severity": "warning",
            "headline": f"Only about {m['cash_buffer_days']:.0f} days of cash cover",
            "detail": (
                f"At the current outflow rate of EUR {m['avg_daily_outflow']:,.0f}/day, "
                f"the bank balance of EUR {m['bank_balance']:,.0f} covers roughly "
                f"{m['cash_buffer_days']:.0f} days without new payouts. One delayed "
                f"payout or one unexpected bill is enough to cause a problem."
            ),
        })

    if m["debt_to_revenue"] > 0.7:
        observations.append({
            "severity": "warning",
            "headline": (
                f"Existing debt is {m['debt_to_revenue']:.2f}x monthly revenue"
            ),
            "detail": (
                f"EUR {m['existing_debt']:,.0f} of debt against "
                f"EUR {m['avg_monthly_revenue']:,.0f} of monthly sales, costing "
                f"EUR {m['monthly_debt_service']:,.0f}/month to service. Most lenders in "
                f"this market cap borrowers between 0.45x and 0.80x, so this is the "
                f"single biggest constraint on raising more."
            ),
        })

    severity_order = {"critical": 0, "warning": 1, "info": 2, "good": 3}
    observations.sort(key=lambda o: severity_order.get(o["severity"], 9))

    # Decide the wording from the same rounded figure that gets displayed, so
    # the sentence never reads "roughly flat 2%".
    mom_pct = round(mom * 100)
    trend_word = (
        "growing" if mom_pct >= 2 else "shrinking" if mom_pct <= -2 else "roughly flat at"
    )
    narrative = (
        f"{p['name']} turned over about EUR {rev_now:,.0f} in the last 30 days, "
        f"{trend_word} {abs(mom_pct):.0f}% on the previous 30 days "
        f"(EUR {rev_prev:,.0f}). Contribution margin is "
        f"{contribution_margin * 100:.0f}%, fixed costs are about "
        f"EUR {fixed_monthly:,.0f}/month, so the business is running at roughly "
        f"EUR {est_monthly_net:+,.0f}/month. There is EUR {m['bank_balance']:,.0f} in "
        f"the bank and EUR {m['platform_balance']:,.0f} still held in the payout queue."
    )

    return {
        "seller_id": ctx.seller_id,
        "name": p["name"],
        "as_of": ctx.as_of.isoformat(),
        "currency": ctx.currency,
        "narrative": narrative,
        "headline_metrics": {
            "revenue_last_30d": round(rev_now, 2),
            "revenue_prior_30d": round(rev_prev, 2),
            "revenue_change_pct": round(mom * 100, 1),
            "revenue_change_pct_previous_period": round(mom_prev * 100, 1),
            "monthly_revenue_run_rate": m["avg_monthly_revenue"],
            "gross_margin": m["gross_margin"],
            "contribution_margin": round(contribution_margin, 4),
            "fixed_costs_monthly": round(fixed_monthly, 2),
            "estimated_monthly_net": round(est_monthly_net, 2),
            "breakeven_monthly_revenue": (
                round(breakeven_revenue, 2) if breakeven_revenue else None),
            "bank_balance": m["bank_balance"],
            "platform_balance": m["platform_balance"],
            "cash_trapped_days_of_sales": round(trapped_days, 1),
            "cash_buffer_days": m["cash_buffer_days"],
            "refund_rate": m["refund_rate"],
            "debt_to_revenue": m["debt_to_revenue"],
        },
        "top_expenses": top_expenses,
        "peer_comparison": {
            "category_label": bench["label"] if bench else None,
            "metrics": comparisons,
            "disclaimer": bench_all["disclaimer"],
        },
        "observations": observations,
        "method_note": (
            "All figures are computed from the sandbox transaction ledger over stated "
            "windows (90 days for revenue and expense mix, "
            f"{config.SALES_BASELINE_WINDOW_DAYS} days for rates). Fixed costs are "
            "inferred from detected recurring payments, so a genuinely irregular bill "
            "may be missed."
        ),
        "disclaimer": (
            "Informational analysis of simulated data. Not accounting, tax or "
            "financial advice, and not a substitute for an accountant."
        ),
    }
