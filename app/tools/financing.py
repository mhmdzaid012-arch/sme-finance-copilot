"""
Explainable financing-option matching.

Two design commitments drive this module:

1. **Every decision is per-criterion.** A product is never "a 72% match". It
   passes or fails each named eligibility test, with the required value and the
   seller's actual value shown side by side. A seller can check our arithmetic,
   and a reviewer can audit it. This is deliberately a transparent rule engine
   rather than a learned scorer.

2. **A rejection must be useful.** Near-misses are returned with the specific
   gap and, where it is knowable, what would have to change to qualify. "No"
   with a reason and a path forward is a better product than a silent filter.

This is emphatically NOT underwriting. It matches a seller against published
eligibility criteria for illustrative product categories. No lender has
assessed anything, and the module says so in its own output.
"""

from __future__ import annotations

from ..store import SellerContext, load_financing_catalog

# Structures that cannot be drawn as general working capital.
RESTRICTED_USE_STRUCTURES = {"equipment_lease", "grant"}


def _amortised_total_cost(principal: float, apr: float, term_months: int) -> float:
    """Total interest paid on a level-payment amortising loan."""
    if apr <= 0 or term_months <= 0:
        return 0.0
    r = apr / 12.0
    n = term_months
    payment = principal * r / (1 - (1 + r) ** -n)
    return payment * n - principal


def _cost_of_capital(product: dict, amount: float, monthly_revenue: float,
                     days_needed: int | None = None) -> dict:
    """
    Normalise wildly different pricing conventions into one comparable shape.

    Two cost figures are returned, and the distinction matters:

    * `total_cost`     - what the product costs over its own natural term.
    * `cost_for_period`- what it costs to hold the money for the number of days
                         the seller actually needs it.

    Ranking on `total_cost` alone is a trap: a 4-month bridge "costs less" than
    a 36-month loan purely because it is shorter, which tells the seller
    nothing about value. `cost_for_period` is what makes a 54-day factoring fee
    and a 36-month loan genuinely comparable.
    """
    cm = product["terms"]["cost_model"]
    kind = cm["type"]
    period_days = days_needed if days_needed and days_needed > 0 else 30

    if kind == "grant":
        co_fund = product["terms"].get("co_funding_required_pct", 0.0)
        return {
            "type": "grant",
            "total_cost": 0.0,
            "cost_for_period": 0.0,
            "cost_basis": "Non-repayable, so there is no cost of capital.",
            "effective_apr": 0.0,
            "own_contribution_required": round(amount * co_fund, 2),
            "explanation": (
                "Non-repayable. No cost of capital"
                + (f", but you must co-fund {co_fund * 100:.0f}% "
                   f"(EUR {amount * co_fund:,.0f}) from your own funds."
                   if co_fund else ".")
            ),
        }

    if kind == "fixed_installment":
        apr = cm["apr"]
        term = int(cm["term_months"])
        total = _amortised_total_cost(amount, apr, term)
        monthly = (amount + total) / term
        penalty = product["terms"].get("early_repayment_penalty", False)
        structure = product["terms"].get("structure", "fixed_installment")
        interest_for_days = amount * apr * (period_days / 365.0)

        if structure == "revolving":
            # A credit line or overdraft charges interest only on the drawn
            # balance for the days it is drawn. Short-period use is exactly
            # what the product is for, so scaling the cost is correct.
            period_cost = interest_for_days
            basis = (f"Revolving facility: interest accrues only on the drawn "
                     f"balance, so EUR {amount:,.0f} drawn for {period_days} days "
                     f"costs about EUR {period_cost:,.0f}.")
            result_extra = {}
        else:
            # A committed term loan is not a short-term instrument. You sign up
            # for the whole term, so the honest comparable cost is the full-term
            # cost - not a pro-rated slice of it. Understating this would make
            # a 36-month subsidised loan look like the cheapest way to cover a
            # 30-day gap, which is not a real option.
            period_cost = total
            basis = (f"Committed {term}-month term: you take on the full facility, "
                     f"so the comparable cost is the whole-term cost of "
                     f"EUR {total:,.0f}, not a pro-rated slice of it.")
            # Simple interest on the full principal can exceed the amortising
            # whole-term cost on short horizons, so clamp: repaying early can
            # never cost more than holding to term.
            early_cost = min(interest_for_days, total)
            result_extra = {
                "if_repaid_early": None if penalty else round(early_cost, 2),
                "early_repayment_note": (
                    "Early repayment is penalised, so the full term cost stands."
                    if penalty else
                    f"Repayable early without penalty: if you genuinely cleared it "
                    f"after {period_days} days the interest would be about "
                    f"EUR {early_cost:,.0f}, but you are still committing "
                    f"to a {term}-month facility to get it."
                ),
            }

        return {
            "type": "fixed_installment",
            "structure": structure,
            "total_cost": round(total, 2),
            "cost_for_period": round(period_cost, 2),
            "cost_basis": basis,
            "effective_apr": round(apr, 4),
            "term_months": term,
            "monthly_payment": round(monthly, 2),
            "term_exceeds_need": structure != "revolving" and term * 30 > period_days * 2,
            "explanation": (
                f"EUR {amount:,.0f} over {term} months at {apr * 100:.1f}% APR: "
                f"about EUR {monthly:,.0f} per month, EUR {total:,.0f} total interest "
                f"if held to term."
            ),
            **result_extra,
        }

    if kind == "revenue_share":
        factor = cm["factor_rate"]
        share = cm["share_of_daily_sales"]
        total_repayable = amount * factor
        total_cost = total_repayable - amount
        daily_collection = (monthly_revenue / 30.0) * share
        est_days = (total_repayable / daily_collection) if daily_collection > 0 else 0
        # Effective APR rises the faster it is repaid - the thing sellers are
        # least often told about revenue-based finance.
        eff_apr = (total_cost / amount) * (365.0 / est_days) if est_days > 0 else 0.0
        return {
            "type": "revenue_share",
            "total_cost": round(total_cost, 2),
            # A fixed factor rate cannot be reduced by repaying early: the full
            # cost is incurred however long you actually needed the money.
            "cost_for_period": round(total_cost, 2),
            "cost_basis": (
                "The factor rate is fixed, so repaying early does not reduce the "
                "cost. You pay the full amount regardless of how long you needed it."
            ),
            "factor_rate": factor,
            "total_repayable": round(total_repayable, 2),
            "share_of_daily_sales": share,
            "estimated_days_to_repay": int(round(est_days)),
            "effective_apr": round(eff_apr, 4),
            "explanation": (
                f"Repay EUR {total_repayable:,.0f} total (factor {factor}) by handing over "
                f"{share * 100:.0f}% of daily sales - roughly EUR {daily_collection:,.0f}/day "
                f"at your current sales rate, so about {int(round(est_days))} days. "
                f"Cost EUR {total_cost:,.0f}, an effective ~{eff_apr * 100:.0f}% APR "
                f"precisely because it is repaid quickly."
            ),
        }

    if kind == "factoring":
        fee_30 = cm["fee_pct_per_30d"]
        advance_rate = cm.get("advance_rate", 1.0)
        periods = period_days / 30.0
        total_cost = amount * fee_30 * periods
        eff_apr = (total_cost / amount) * (365.0 / period_days) if period_days > 0 else 0.0
        return {
            "type": "factoring",
            "total_cost": round(total_cost, 2),
            "cost_for_period": round(total_cost, 2),
            "cost_basis": (
                f"Charged per 30 days outstanding, so cost scales with the "
                f"{period_days} days you actually need it."
            ),
            "fee_pct_per_30d": fee_30,
            "advance_rate": advance_rate,
            "days_outstanding": period_days,
            "effective_apr": round(eff_apr, 4),
            "explanation": (
                f"EUR {amount:,.0f} advanced for {period_days} days at "
                f"{fee_30 * 100:.1f}% per 30 days costs about EUR {total_cost:,.0f} "
                f"(effective ~{eff_apr * 100:.0f}% APR). Repaid automatically from "
                f"your next payout rather than out of future profit."
            ),
        }

    return {"type": kind, "total_cost": 0.0, "cost_for_period": 0.0,
            "effective_apr": 0.0, "cost_basis": "",
            "explanation": "Cost model not recognised."}


def _evaluate_eligibility(product: dict, ctx: SellerContext, amount: float) -> list[dict]:
    """
    Return one row per applicable criterion. Each row is a complete, checkable
    statement: what was required, what the seller actually is, and the verdict.
    """
    e = product.get("eligibility", {})
    m = ctx.metrics
    p = ctx.profile
    checks: list[dict] = []

    def check(name: str, label: str, required, actual, passed: bool, hint: str = "") -> None:
        checks.append({
            "criterion": name,
            "label": label,
            "required": required,
            "actual": actual,
            "passed": bool(passed),
            "hint": hint,
        })

    rev = m["avg_monthly_revenue"]

    if "min_monthly_revenue" in e:
        need = e["min_monthly_revenue"]
        check("min_monthly_revenue", "Minimum monthly revenue",
              f"EUR {need:,.0f}", f"EUR {rev:,.0f}", rev >= need,
              "" if rev >= need else f"Revenue needs to grow by EUR {need - rev:,.0f}/month.")

    if "max_monthly_revenue" in e:
        cap = e["max_monthly_revenue"]
        check("max_monthly_revenue", "Maximum monthly revenue (scheme cap)",
              f"EUR {cap:,.0f}", f"EUR {rev:,.0f}", rev <= cap,
              "" if rev <= cap else "This business is now too large for this scheme.")

    if "min_months_trading" in e:
        need = e["min_months_trading"]
        have = p["months_trading"]
        check("min_months_trading", "Minimum trading history",
              f"{need} months", f"{have} months", have >= need,
              "" if have >= need else f"Eligible in {need - have} more months of trading.")

    if "max_debt_to_revenue" in e:
        cap = e["max_debt_to_revenue"]
        have = m["debt_to_revenue"]
        headroom = (cap - have) * rev
        check("max_debt_to_revenue", "Maximum existing debt (x monthly revenue)",
              f"{cap:.2f}x", f"{have:.2f}x", have <= cap,
              "" if have <= cap else
              f"Existing debt is EUR {abs(headroom):,.0f} above this lender's ceiling; "
              f"paying down that much would qualify.")

    if "max_refund_rate" in e:
        cap = e["max_refund_rate"]
        have = m["refund_rate"]
        check("max_refund_rate", "Maximum refund rate",
              f"{cap * 100:.1f}%", f"{have * 100:.1f}%", have <= cap,
              "" if have <= cap else
              f"Refund rate is {(have - cap) * 100:.1f} points too high; "
              f"reducing returns would open this option.")

    if "max_chargeback_rate" in e:
        cap = e["max_chargeback_rate"]
        have = m["chargeback_rate"]
        check("max_chargeback_rate", "Maximum chargeback rate",
              f"{cap * 100:.2f}%", f"{have * 100:.2f}%", have <= cap)

    if "regions" in e:
        check("regions", "Eligible regions", ", ".join(e["regions"]),
              p["region"], p["region"] in e["regions"])

    if "countries" in e:
        check("countries", "Eligible countries", ", ".join(e["countries"]),
              p["country"], p["country"] in e["countries"])

    if "categories_excluded" in e:
        excl = e["categories_excluded"]
        check("categories_excluded", "Excluded business categories",
              ", ".join(excl), p["category"], p["category"] not in excl,
              "" if p["category"] not in excl else "This lender does not fund this category.")

    if "categories_included" in e:
        inc = e["categories_included"]
        check("categories_included", "Permitted business categories",
              ", ".join(inc), p["category"], p["category"] in inc,
              "" if p["category"] in inc else "This scheme is limited to other categories.")

    if "min_amount" in e:
        need = e["min_amount"]
        check("min_amount", "Minimum facility size",
              f"EUR {need:,.0f}", f"EUR {amount:,.0f}", amount >= need,
              "" if amount >= need else
              f"You would have to borrow at least EUR {need:,.0f} - more than you need.")

    if "max_amount" in e:
        cap = e["max_amount"]
        check("max_amount", "Maximum facility size",
              f"EUR {cap:,.0f}", f"EUR {amount:,.0f}", amount <= cap)

    if "max_multiple_of_monthly_revenue" in e:
        mult = e["max_multiple_of_monthly_revenue"]
        cap = rev * mult
        check("max_multiple_of_monthly_revenue",
              f"Maximum advance ({mult}x monthly revenue)",
              f"EUR {cap:,.0f}", f"EUR {amount:,.0f}", amount <= cap,
              "" if amount <= cap else
              f"This lender would cap you at about EUR {cap:,.0f}.")

    if e.get("requires_platform_balance"):
        bal = m["platform_balance"]
        advance_rate = product["terms"]["cost_model"].get("advance_rate", 0.85)
        available = bal * advance_rate
        check("requires_platform_balance", "Requires funds held in payout queue",
              f"at least EUR {amount:,.0f} advanceable",
              f"EUR {bal:,.0f} held -> EUR {available:,.0f} advanceable at "
              f"{advance_rate * 100:.0f}%",
              available >= amount,
              "" if available >= amount else
              f"Your payout queue only supports about EUR {available:,.0f} right now; "
              f"this could cover part of the need.")

    return checks


def match_financing(ctx: SellerContext, amount: float | None = None,
                    purpose: str = "working_capital",
                    days_needed: int | None = None,
                    days_until_needed: int | None = None) -> dict:
    """
    Match a seller against the illustrative catalog.

    `amount` defaults to the shortfall the forecaster identified, so the two
    tools compose: "you are EUR 9,000 short for 54 days, starting in 15 days"
    flows straight into "here is what covering that would cost, excluding
    anything that cannot be arranged within 15 days".

    Two distinct time parameters, which are easy to conflate and mean very
    different things:

    * `days_needed`       - how long the money is needed FOR. Drives cost.
    * `days_until_needed` - how long there is to ARRANGE it. Drives feasibility;
                            a facility that lands after the payment is due is
                            worthless at any price.
    """
    catalog = load_financing_catalog()
    m = ctx.metrics

    if amount is None or amount <= 0:
        amount = max(1000.0, round(m["avg_monthly_revenue"] * 0.5, -2))
    amount = float(amount)

    eligible: list[dict] = []
    near_miss: list[dict] = []
    wrong_purpose: list[dict] = []

    for product in catalog["products"]:
        checks = _evaluate_eligibility(product, ctx, amount)
        failed = [c for c in checks if not c["passed"]]
        cost = _cost_of_capital(product, amount, m["avg_monthly_revenue"], days_needed)

        restricted = (
            product["type"] in RESTRICTED_USE_STRUCTURES
            or product["terms"].get("use_of_funds_restricted", False)
        )
        entry = {
            "id": product["id"],
            "name": product["name"],
            "provider": product["provider"],
            "type": product["type"],
            "description": product["description"],
            "requested_amount": round(amount, 2),
            "cost": cost,
            "speed_days": product["terms"]["speed_days"],
            "collateral_required": product["terms"].get("collateral_required", False),
            "personal_guarantee": product["terms"].get("personal_guarantee", False),
            "use_restricted": restricted,
            "notes": product.get("notes", ""),
            "checks": checks,
            "failed_criteria": [c["criterion"] for c in failed],
        }

        # Funds that legally cannot be spent on the stated purpose are not
        # options, however cheap they look. Keeping them in a separate bucket
        # is more honest than ranking them low and hoping nobody clicks.
        if restricted and purpose == "working_capital":
            entry["excluded_reason"] = (
                "Funds from this product are ring-fenced (equipment, capital "
                "expenditure or a specific project) and cannot be drawn as "
                "general working capital."
            )
            if not failed:
                wrong_purpose.append(entry)
            continue

        if not failed:
            eligible.append(entry)
        elif len(failed) <= 2:
            entry["why_not"] = [
                {"label": c["label"], "required": c["required"],
                 "actual": c["actual"], "hint": c["hint"]}
                for c in failed
            ]
            near_miss.append(entry)

    # --- ranking -----------------------------------------------------------
    # Cost for the period actually needed, cheapest first - but a facility that
    # cannot be arranged before the money is due is worthless at any price, so
    # lead time gates the ranking whenever there is a deadline.
    def is_too_slow(entry: dict) -> bool:
        return (
            days_until_needed is not None
            and entry["speed_days"] > days_until_needed
        )

    for entry in eligible + near_miss:
        entry["too_slow"] = is_too_slow(entry)
        if entry["too_slow"]:
            entry["timing_warning"] = (
                f"Takes about {entry['speed_days']} days to arrange, but your balance "
                f"drops below your safety buffer in {days_until_needed} days. It cannot "
                f"be the first line of defence this time."
            )

    eligible.sort(key=lambda e: (e["too_slow"], e["cost"]["cost_for_period"], e["speed_days"]))
    near_miss.sort(key=lambda e: (len(e["failed_criteria"]), e["too_slow"]))

    in_time = [e for e in eligible if not e["too_slow"]]
    cheapest = in_time[0] if in_time else (eligible[0] if eligible else None)
    fastest = min(eligible, key=lambda e: e["speed_days"]) if eligible else None

    summary_lines: list[str] = []
    if cheapest:
        period_note = f" for the {days_needed} days you need it" if days_needed else ""
        summary_lines.append(
            f"{len(eligible)} of {len(catalog['products'])} illustrative products match "
            f"a EUR {amount:,.0f} requirement. Lowest cost{period_note}: "
            f"{cheapest['name']} at EUR {cheapest['cost']['cost_for_period']:,.0f}."
        )
        if fastest and fastest["id"] != cheapest["id"]:
            summary_lines.append(
                f"Fastest to arrange: {fastest['name']} in ~{fastest['speed_days']} day(s), "
                f"costing EUR {fastest['cost']['cost_for_period']:,.0f}."
            )
    else:
        summary_lines.append(
            f"No product in the illustrative catalog matches a EUR {amount:,.0f} "
            f"requirement for this seller on published criteria."
        )
    if near_miss:
        summary_lines.append(
            f"{len(near_miss)} product(s) fail on one or two criteria only - listed with "
            f"the exact gap so you can see what would have to change."
        )

    return {
        "seller_id": ctx.seller_id,
        "requested_amount": round(amount, 2),
        "purpose": purpose,
        "days_needed": days_needed,
        "days_until_needed": days_until_needed,
        "seller_snapshot": {
            "monthly_revenue": m["avg_monthly_revenue"],
            "months_trading": m["months_trading"],
            "debt_to_revenue": m["debt_to_revenue"],
            "refund_rate": m["refund_rate"],
            "chargeback_rate": m["chargeback_rate"],
            "platform_balance": m["platform_balance"],
            "region": ctx.profile["region"],
            "country": ctx.profile["country"],
            "category": ctx.profile["category"],
        },
        "eligible_count": len(eligible),
        "eligible": eligible,
        "near_miss": near_miss,
        "excluded_wrong_purpose": wrong_purpose,
        "summary": " ".join(summary_lines),
        "disclaimer": (
            "Matching against published eligibility criteria for ILLUSTRATIVE product "
            "categories. This is not underwriting, not a credit decision, not an offer, "
            "and not financial advice. No lender has assessed this business."
        ),
        "catalog_disclaimer": catalog["disclaimer"],
    }
