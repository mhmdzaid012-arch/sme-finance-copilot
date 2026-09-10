"""
Sandbox data access and derived metrics.

This is the only module that touches the dataset on disk. Everything above it
works with `SellerContext` objects, which makes it straightforward to swap the
sandbox for a real (permissioned, read-only) data source later without
touching the tools or the agent.
"""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

from . import config


@dataclass(frozen=True)
class Transaction:
    txn_id: str
    seller_id: str
    date: date
    ledger: str  # "platform" | "bank"
    type: str  # sale | platform_fee | refund | chargeback | payout | expense
    category: str
    amount: float  # signed
    counterparty: str
    memo: str


@dataclass
class SellerContext:
    """A seller plus their transaction history and derived metrics."""

    profile: dict
    transactions: list[Transaction]
    as_of: date
    metrics: dict = field(default_factory=dict)

    @property
    def seller_id(self) -> str:
        return self.profile["seller_id"]

    @property
    def name(self) -> str:
        return self.profile["name"]

    @property
    def currency(self) -> str:
        return self.profile.get("currency", "EUR")

    def window(self, days: int, types: tuple[str, ...] | None = None) -> list[Transaction]:
        start = self.as_of - timedelta(days=days - 1)
        return [
            t for t in self.transactions
            if start <= t.date <= self.as_of and (types is None or t.type in types)
        ]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_sellers_file() -> dict:
    path = config.DATA_DIR / "sellers.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_transactions() -> tuple[Transaction, ...]:
    path = config.DATA_DIR / "transactions.csv"
    out: list[Transaction] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Transaction(
                txn_id=row["txn_id"],
                seller_id=row["seller_id"],
                date=date.fromisoformat(row["date"]),
                ledger=row["ledger"],
                type=row["type"],
                category=row["category"],
                amount=float(row["amount"]),
                counterparty=row["counterparty"],
                memo=row["memo"],
            ))
    return tuple(out)


@lru_cache(maxsize=1)
def load_financing_catalog() -> dict:
    path = config.DATA_DIR / "financing_products.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_sellers() -> list[dict]:
    """Lightweight seller directory for the UI."""
    out = []
    for p in _load_sellers_file()["sellers"]:
        ctx = get_seller(p["seller_id"])
        out.append({
            "seller_id": p["seller_id"],
            "name": p["name"],
            "owner": p["owner"],
            "category": p["category"],
            "country": p["country"],
            "months_trading": p["months_trading"],
            "monthly_revenue": ctx.metrics["avg_monthly_revenue"],
            "bank_balance": ctx.metrics["bank_balance"],
            "platform_balance": ctx.metrics["platform_balance"],
            "persona_note": p.get("persona_note", ""),
        })
    return out


def dataset_disclaimer() -> str:
    return _load_sellers_file()["disclaimer"]


def get_seller(seller_id: str, as_of: date | None = None) -> SellerContext:
    as_of = as_of or config.AS_OF
    profile = next(
        (p for p in _load_sellers_file()["sellers"] if p["seller_id"] == seller_id),
        None,
    )
    if profile is None:
        raise KeyError(f"unknown seller: {seller_id}")
    txns = [t for t in _load_transactions() if t.seller_id == seller_id and t.date <= as_of]
    ctx = SellerContext(profile=profile, transactions=txns, as_of=as_of)
    ctx.metrics = compute_metrics(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------

def _sum(txns: list[Transaction], types: tuple[str, ...]) -> float:
    return sum(t.amount for t in txns if t.type in types)


def compute_metrics(ctx: SellerContext) -> dict:
    """
    All rates are trailing measures over an explicit window, so every number
    the copilot quotes can be traced back to a window and a set of rows.
    """
    w90 = ctx.window(90)
    w56 = ctx.window(config.SALES_BASELINE_WINDOW_DAYS)

    sales_90 = _sum(w90, ("sale",))
    days_90 = min(90, (ctx.as_of - min((t.date for t in ctx.transactions), default=ctx.as_of)).days + 1)
    avg_monthly_revenue = (sales_90 / days_90 * 30.0) if days_90 else 0.0

    sales_56 = _sum(w56, ("sale",)) or 1e-9
    fee_rate = abs(_sum(w56, ("platform_fee",))) / sales_56
    refund_rate = abs(_sum(w56, ("refund",))) / sales_56
    chargeback_rate = abs(_sum(w56, ("chargeback",))) / sales_56

    cogs_90 = abs(sum(t.amount for t in w90 if t.category == "cogs"))
    gross_margin = 1.0 - (cogs_90 / sales_90) if sales_90 else 0.0

    bank_balance = ctx.profile["opening_bank_balance"] + sum(
        t.amount for t in ctx.transactions if t.ledger == "bank"
    )
    platform_balance = sum(t.amount for t in ctx.transactions if t.ledger == "platform")

    # Average daily net bank burn excluding payouts, i.e. the rate at which
    # cash leaves the account between payouts.
    outflow_90 = abs(sum(
        t.amount for t in w90
        if t.ledger == "bank" and t.amount < 0
    ))
    daily_outflow = outflow_90 / days_90 if days_90 else 0.0
    buffer_days = (bank_balance / daily_outflow) if daily_outflow > 0 else float("inf")

    existing_debt = float(ctx.profile.get("existing_debt", 0.0))
    debt_to_revenue = (existing_debt / avg_monthly_revenue) if avg_monthly_revenue else 0.0

    expense_breakdown: dict[str, float] = {}
    for t in w90:
        if t.ledger == "bank" and t.amount < 0 and t.type == "expense":
            expense_breakdown[t.category] = expense_breakdown.get(t.category, 0.0) + abs(t.amount)

    return {
        "as_of": ctx.as_of.isoformat(),
        "avg_monthly_revenue": round(avg_monthly_revenue, 2),
        "revenue_90d": round(sales_90, 2),
        "platform_fee_rate": round(fee_rate, 4),
        "refund_rate": round(refund_rate, 4),
        "chargeback_rate": round(chargeback_rate, 4),
        "gross_margin": round(gross_margin, 4),
        "bank_balance": round(bank_balance, 2),
        "platform_balance": round(platform_balance, 2),
        "existing_debt": round(existing_debt, 2),
        "monthly_debt_service": round(float(ctx.profile.get("monthly_debt_service", 0.0)), 2),
        "debt_to_revenue": round(debt_to_revenue, 4),
        "avg_daily_outflow": round(daily_outflow, 2),
        "cash_buffer_days": round(buffer_days, 1) if buffer_days != float("inf") else None,
        "months_trading": ctx.profile["months_trading"],
        "safety_buffer": float(ctx.profile.get("safety_buffer", config.DEFAULT_SAFETY_BUFFER)),
        "expense_breakdown_90d": {k: round(v, 2) for k, v in sorted(
            expense_breakdown.items(), key=lambda kv: -kv[1])},
        "windows": {
            "revenue": "trailing 90 days",
            "rates": f"trailing {config.SALES_BASELINE_WINDOW_DAYS} days",
        },
    }


# ---------------------------------------------------------------------------
# Recurring-payment detection (used by the forecaster)
# ---------------------------------------------------------------------------

def detect_recurring(ctx: SellerContext, lookback_days: int = 180) -> list[dict]:
    """
    Group historical bank outflows by (counterparty, category) and keep the
    groups that repeat on a stable cadence. Deliberately rule-based: a seller
    can read the rule and check it, which matters for an explainability score.
    """
    start = ctx.as_of - timedelta(days=lookback_days)
    groups: dict[tuple[str, str], list[Transaction]] = {}
    for t in ctx.transactions:
        if t.ledger != "bank" or t.amount >= 0 or t.type != "expense":
            continue
        if t.date < start:
            continue
        # Per-order variable costs are modelled as a share of sales instead.
        if t.category in {"cogs", "shipping", "advertising"}:
            continue
        groups.setdefault((t.counterparty, t.category), []).append(t)

    recurring: list[dict] = []
    for (counterparty, category), items in groups.items():
        if len(items) < config.RECURRING_MIN_OCCURRENCES:
            continue
        items.sort(key=lambda t: t.date)
        gaps = [(b.date - a.date).days for a, b in zip(items, items[1:])]
        if not gaps:
            continue
        gap_stddev = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
        if gap_stddev > config.RECURRING_MAX_GAP_STDDEV_DAYS:
            continue
        median_gap = statistics.median(gaps)
        amounts = [abs(t.amount) for t in items]
        recurring.append({
            "counterparty": counterparty,
            "category": category,
            "amount": round(statistics.median(amounts), 2),
            "cadence_days": int(round(median_gap)),
            "last_seen": items[-1].date.isoformat(),
            "occurrences": len(items),
            "gap_stddev_days": round(gap_stddev, 2),
            "day_of_month": items[-1].date.day,
        })

    recurring.sort(key=lambda r: -r["amount"])
    return recurring
