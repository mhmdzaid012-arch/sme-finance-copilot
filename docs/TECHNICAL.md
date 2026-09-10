# Technical documentation

SME Finance Copilot — system architecture, core algorithms, security design.

Fintechathon International Track, Topic E. All data is simulated.

---

## 1. The problem being modelled

An e-commerce micro-seller holds money in two places, and that split is the entire
reason this product exists:

```
platform balance = sales − platform fees − refunds − payouts
bank balance      = opening + payouts − expenses − chargebacks
```

Sales accrue into the **platform balance** and reach the **bank balance** only on the
marketplace's payout schedule, after a hold period, minus a rolling reserve. A seller
can be profitable every month and still miss a supplier payment, because profit and
liquidity are separated by the payout mechanics.

Most consumer budgeting tools model a single account and therefore cannot represent
this at all. Modelling the two ledgers explicitly is what lets the copilot say *"you
have €5,007 you have already earned and cannot spend, and that is why you are short"*.

### Why this niche

Transaction-shaped finances make realistic sandbox data tractable, cash-flow alerts
have genuine causes (payout holds, seasonal peaks, chargebacks), and the financing
products that actually serve these businesses — revenue-based finance, marketplace
factoring, microfinance — map cleanly onto rule-based eligibility criteria. The
segment is also materially underbanked, which is where the product has social value
as well as commercial logic.

---

## 2. System architecture

```
browser ──► FastAPI (app/main.py) ──► Agent (app/agent.py) ──► tools ──► store ──► data/
                                          │
                                          ├── security/permissions.py
                                          ├── security/guardrails.py
                                          └── security/audit.py
```

Every turn follows one pipeline, in both modes:

```
input guardrails → scope check → plan → tool dispatch → output guardrails → reply
                                          │
                              permission check + audit per call
```

### Layers

| Layer | Responsibility | Why it is separate |
|---|---|---|
| `store.py` | Sandbox ledger access, derived metrics, recurring-payment detection | The only module touching data on disk, so the sandbox could be swapped for a permissioned read-only feed without changing any tool |
| `tools/*` | All financial reasoning | Deterministic and unit-testable; no model involvement |
| `agent.py` | Planning, guardrail pipeline, narrative | The only place a model appears |
| `security/*` | Tiers, injection defence, audit | Enforced around dispatch, so no tool can be reached without passing through it |

### Two execution modes

The agent runs with a language model (`ANTHROPIC_API_KEY` present) or with a
deterministic intent router. In both cases **the tools compute every figure**. The
model's role is limited to choosing tools and phrasing results.

This is a deliberate reliability boundary. A model that hallucinates a balance in a
financial product is not a cosmetic defect. It also means the demo is reproducible
without credentials, and that an API outage degrades phrasing rather than correctness
(`run_llm` falls back to the offline path and says so).

---

## 3. Core algorithm: cash-flow forecasting

`app/tools/forecast.py`. Rule-based and deterministic — not a learned model. Every euro
traces to one of five named components, which is what makes the output defensible to a
seller and auditable by a reviewer. An opaque model would score worse on
explainability and could not be justified in a compliance review.

### 3.1 Projected sales

```
sales(d) = weekday_baseline[weekday(d)] × growth^(days_ahead / 28) × seasonality(month)
```

- **Weekday baseline** — mean gross sales per weekday over a 56-day window,
  *de-seasonalised* first so the seasonality multiplier is not applied twice.
- **Growth** — trailing 28 days versus the prior 28 days, **clamped to [0.80, 1.30]**.
  Unclamped ratio extrapolation is the classic way a naive forecaster produces
  nonsense from a good fortnight.
- **Seasonality** — documented multiplicative monthly factors (Q4 uplift, August lull),
  damped per category. Constants live in `app/config.py:SEASONALITY`.

### 3.2 Payout releases

The mechanism that matters most. A pipeline of net accrual per sale-date is maintained:

```
net_accrual(d) = gross_sales(d) × (1 − fee_rate − refund_rate)
```

On each scheduled payout date, everything with a sale-date on or before
`payout_date − hold_days` is released:

```
payout = released × (1 − reserve_pct) + reserve_held_from_previous_payout
reserve_held = released × reserve_pct
```

The rolling reserve is modelled as **rolling**: withheld on one payout, released on the
next. Treating it as a permanent haircut — the intuitive but wrong reading — makes
every seller look structurally insolvent, because it silently removes 2–8% of all
revenue forever. This was caught during development by the unit economics not
reconciling, and is now covered by `test_rolling_reserve_does_not_leak_cash`.

The pipeline is seeded from **actual history**, not from state written by the data
generator. `payout_state()` replays the payout schedule across the real ledger to
recover which sale-dates have already been released and how much reserve is held. This
is what makes the forecaster valid for an arbitrary `as_of` — and therefore
backtestable at all.

### 3.3–3.5 Outflows

- **Variable costs** — COGS, shipping and advertising as a measured share of sales over
  the 56-day window, incurred on the sale date.
- **Recurring fixed costs** — detected from history by grouping bank outflows on
  `(counterparty, category)` and keeping groups with ≥3 occurrences whose inter-payment
  gaps have a standard deviation ≤4 days. Per-order variable categories are excluded so
  they are never double-counted against the sales-linked projection.
- **Scheduled obligations** — declared future bills from the seller's profile.

### 3.6 Risk findings

The daily walk yields the balance path, from which:

- `trough_balance` / `trough_date`
- `goes_negative`, `first_negative_date`
- `shortfall_to_buffer` — the amount needed to hold the safety buffer throughout
- `suggested_bridge_days` — **how long** the money is needed for
- `days_until_first_shortfall` — **how long there is to arrange it**
- `primary_drivers` — attributed across the whole drawdown

**The two time quantities are distinct and conflating them is a real bug.** An early
version used "days needed" as the arranging deadline, which ranked a 1-day merchant
cash advance above a microloan at a fifth of the cost. They are now separate inputs to
the financing engine.

**Driver attribution** aggregates events from today to the trough, not a trailing
window. Amara's trough is on 18 October but its cause is a payment on 25 September; a
14-day lookback blamed the ordinary bills that happened to land near the low point.

### 3.7 Measured accuracy

`backtest()` forecasts from a past date and compares against the actual ledger.

| Seller | 30d | 45d | 60d |
|---|---:|---:|---:|
| amara-prints | 3.8% | 2.8% | 1.7% |
| kofi-coffee | 0.9% | 0.8% | 2.4% |
| linas-ceramics | 2.7% | 0.9% | 1.4% |
| techfix-parts | 2.0% | 4.5% | 6.5% |

Adjusted absolute error as a percentage of monthly revenue. **Mean 2.5%, worst 6.5%.**
Regenerate with `python scripts/generate_evidence.py`; the bound is asserted by
`test_backtest_accuracy_within_declared_bounds`.

Error is normalised against **monthly revenue**, not closing balance. Percentage-of-
balance flatters large-balance sellers and punishes small ones: Amara's €421 miss is
13.2% of her €3,180 balance but 3.8% of her monthly revenue, and the latter is the fair
basis for comparing forecast quality across businesses of different sizes.

`adjusted_error` excludes one-off payments that were neither recurring nor declared
when the forecast was made. This is disclosed, not hidden, because it is the method's
principal limitation: Amara's raw 30-day error is €4,921, of which €4,500 is a single
undeclared supplier deposit. **A rule-based forecaster cannot see lumpy commitments the
seller has not told it about** — which is precisely why the product asks sellers to
declare known upcoming bills, and why the alert copy nudges toward that.

---

## 4. Core algorithm: financing matching

`app/tools/financing.py`. A transparent rule engine, not a learned scorer.

### 4.1 Per-criterion evaluation

A product is never "a 72% match". Each applicable criterion produces a complete,
checkable row: what was required, the seller's actual value, and the verdict.

```
min_monthly_revenue · max_monthly_revenue · min_months_trading
max_debt_to_revenue · max_refund_rate · max_chargeback_rate
regions · countries · categories_included / excluded
min_amount · max_amount · max_multiple_of_monthly_revenue
requires_platform_balance
```

A product is eligible only if **every** criterion passes. Products failing one or two
become **near-misses**, returned with the gap quantified and, where knowable, the
remedy — for example *"existing debt is €8,200 above this lender's ceiling; paying down
that much would qualify"*. A rejection that explains itself is a better product than a
silent filter, and it is what makes the tool useful to a seller who does not yet
qualify for anything.

### 4.2 True cost of capital

Four pricing conventions are normalised into one comparable shape. Two figures are
returned, and the distinction is the substantive part:

- `total_cost` — cost over the product's own natural term.
- `cost_for_period` — cost of holding the money for the days actually needed.

Ranking on `total_cost` is a trap: a 4-month bridge "costs less" than a 36-month loan
purely because it is shorter. `cost_for_period` is computed by structure:

| Structure | `cost_for_period` | Rationale |
|---|---|---|
| Revolving / overdraft | `amount × apr × days/365` | Interest accrues only on the drawn balance; short use is the product's purpose |
| Factoring / trade credit | `amount × fee_30 × days/30` | Priced per 30 days outstanding |
| Committed term loan | full-term cost | You commit to the whole facility. Pro-rating would make a 36-month subsidised microloan look like the cheapest way to cover a 30-day gap, which is not a real option |
| Revenue share | full cost | **A fixed factor rate cannot be reduced by repaying early** |
| Grant | 0, plus co-funding disclosed | Non-repayable |

For committed-term products an `if_repaid_early` figure is still disclosed separately
(clamped so it can never exceed the full-term cost), alongside the reminder that the
seller is committing to the full facility to obtain it.

Revenue-share products also report `effective_apr`, which **rises the faster they are
repaid** — the single most under-disclosed fact about revenue-based finance. A merchant
cash advance is kept in the catalog deliberately so the copilot can show what the fast
option really costs: for Amara it is €2,530 against €299, an effective ~71% APR.

### 4.3 Ranking

```
sort by (too_slow, cost_for_period, speed_days)
too_slow = speed_days > days_until_needed
```

A facility that cannot be arranged before the money is due is worthless at any price,
so lead time gates the ranking rather than merely influencing it — but such products
are **flagged and retained**, with the note that they are worth arranging before the
next peak. Products whose funds are ring-fenced (equipment, capex, project grants) are
moved to a separate `excluded_wrong_purpose` bucket for working-capital requests
rather than ranked low, since they are not options at all.

---

## 5. Business analysis

`app/tools/analysis.py`. Translation, not calculation.

```
contribution_margin = 1 − (variable_costs + platform_fees + refunds) / sales
estimated_monthly_net = revenue × contribution_margin − fixed_costs
breakeven_revenue = fixed_costs / contribution_margin
cash_trapped_days = platform_balance / daily_sales
```

Observations are generated conditionally and sorted by severity, so the seller gets the
two or three numbers that could change a decision — not a wall of ratios. Peer
comparison uses p25/median/p75 bands per category from `data/benchmarks.json`, which
are **synthetic and labelled as such in every response**.

The most product-defining output is `cash_trapped_days`: Amara has 13.7 days of sales
earned but unspendable. Almost nothing in the market shows a seller that number.

---

## 6. Security design

Full self-assessment and known-risk list: **[SECURITY.md](SECURITY.md)**. Summary:

### Permission tiers

| Tier | Scope | Enforcement |
|---|---|---|
| `T0_READ` | Read simulated data | Registry lookup |
| `T1_RECOMMEND` | Analysis, forecasts, matches, alerts. No side effects | **Session default** |
| `T2_ACTION` | Real-world consequences | Staged only; human confirmation required |

A tool absent from `TOOL_REGISTRY` cannot be dispatched at all.

### Why the agent cannot self-approve

A T2 call does not act. It returns a `pending_confirmation` with a plain-language
consequence and a token that is **server-generated, single-use, expiring (600s), and
bound to a SHA-256 of the exact payload shown to the user** — so a payload mutated
between staging and approval is rejected.

`confirm_action` is **not in the agent tool registry**. A fully prompt-injected model
has no capability with which to approve its own action. This is the difference between
"we told the model not to" and "the model cannot", and it is asserted by
`test_agent_has_no_capability_to_confirm_its_own_actions`.

Confirmation decisions are audited inside `confirm_action` itself rather than by
callers, so no code path can execute an action without recording the decision.

### Prompt injection

The threat that matters here is **indirect** injection: a financial copilot reads
customer order notes, refund reasons and counterparty names, none of which the seller
controls. The sandbox ledger therefore contains a **real planted attack** in an order
note, so the defence is demonstrated against actual data.

Three layers: `scan_text` (11 pattern families, higher severity when the text arrives
in *data* rather than user input, since a customer note has no business addressing the
model); `wrap_untrusted` (redacts instruction-like spans, then fences the remainder in
an explicit untrusted-data block — redacting rather than dropping the row so the seller
can still see a suspicious note exists); and `check_output` (blocks claims of approval,
guarantees, certainty, or account numbers in output).

Pattern matching is explicitly **not** presented as a solution to prompt injection. It
raises the cost of an attack. The architectural control is what bounds the damage.

Guardrails are also tested for false positives: `test_benign_finance_questions_are_not_flagged`
asserts that ordinary questions pass, because a guardrail that fires on real usage gets
switched off in production.

### Audit log

Append-only JSONL where each record carries the SHA-256 of its predecessor. Editing,
reordering, inserting or deleting any record breaks the chain, detectable by
`verify_chain()` using only the file's own contents. Tokens are redacted and long
values truncated. The log doubles as the required execution evidence.

---

## 7. Reproducibility

Everything is deterministic. `scripts/generate_data.py` uses fixed per-seller seeds; the
dataset is pinned to `as_of = 2026-09-10`; offline mode involves no sampling.

```bash
python scripts/generate_data.py       # 4,782 transactions, 4 sellers
python scripts/generate_evidence.py   # 13 scenarios, 61 audit records, 12 backtests
pytest -q                             # 132 tests
```

Test coverage by area: forecasting mechanics and measured accuracy (27), financing cost
maths and eligibility reasoning (30), security — tiers, injection, audit integrity (29),
agent pipeline and HTTP API (46).

## 8. Known limitations

Stated here in brief; expanded with likelihood, impact and remediation in
[SECURITY.md](SECURITY.md).

1. **Undeclared one-off payments are unforecastable.** The dominant source of forecast
   error. Mitigated by asking sellers to declare known bills, not solved.
2. **Rule-based forecasting cannot anticipate structural breaks** — a marketplace
   changing its payout terms, a category collapsing, a supplier failing.
3. **Eligibility matching is not underwriting.** Real lenders use bureau data,
   affordability models and manual review. Matching against published criteria will
   both over- and under-predict real decisions.
4. **Synthetic benchmarks.** Peer bands are constructed, not measured, and are labelled
   as such in every response that uses them.
5. **Pattern-based injection defence is incomplete** by nature.
6. **Demo-grade session handling.** In-process sessions, no authentication.
