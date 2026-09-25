# Technical documentation

SME Finance Copilot: system architecture, core algorithms, and security design.

Fintechathon International Track, Topic E. All data is simulated.

---

## 1. The problem being modelled

An e-commerce micro-seller keeps money in two places, and that split is the whole
reason this product exists:

```
platform balance = sales - platform fees - refunds - payouts
bank balance     = opening + payouts - expenses - chargebacks
```

Sales go into the **platform balance**. They reach the **bank balance** only on the
marketplace's payout schedule, after a hold period and minus a rolling reserve. A
seller can have cash left over every month and still miss a supplier payment, because
the payout mechanics sit between earning money and being able to spend it.

Most consumer budgeting tools model a single account, so they can't represent this at
all. Modelling both ledgers explicitly is what lets the copilot say *"you have money
you've already earned and can't spend, and that's why you're short"*.

### Why this niche

The finances of these sellers are transaction-shaped (orders, fees, refunds, payouts),
which makes realistic sandbox data tractable. The cash-flow alerts have real causes:
payout holds, seasonal stock purchases, chargebacks. The financing products that
actually serve these businesses (revenue-based finance, marketplace factoring,
microfinance) map cleanly onto rule-based eligibility criteria. The segment is also
underbanked, so the product has social value as well as commercial logic.

---

## 2. System architecture

```
browser ──► FastAPI (app/main.py) ──► Agent (app/agent.py) ──► tools ──► store ──► data/
                                          │
                                          ├── security/permissions.py
                                          ├── security/guardrails.py
                                          └── security/audit.py
```

Every turn follows the same pipeline in both modes:

```
input guardrails → scope check → plan → tool dispatch → output guardrails → reply
                                          │
                              permission check + audit per call
```

| Layer | Responsibility | Why it is separate |
|---|---|---|
| `store.py` | Sandbox ledger access, derived metrics, recurring-payment detection | The only module that reads data from disk, so the sandbox could be swapped for a permissioned read-only feed without touching any tool |
| `tools/*` | All financial reasoning | Deterministic and unit-testable, with no model involved |
| `agent.py` | Planning, the guardrail pipeline, the narrative | The only place a model appears |
| `security/*` | Tiers, injection defence, audit | Enforced around dispatch, so no tool can be reached without passing through it |
| `facts.py` | Every figure quoted outside the code | Keeps the documents and the deck in step with the system (section 8) |

The agent runs with a language model (when `ANTHROPIC_API_KEY` is present) or with a
deterministic intent router. **In both cases the tools compute every figure.** The
model only chooses tools and phrases the results. This is a deliberate reliability
boundary: a financial product must not invent a balance. It also means the demo can be
reproduced without credentials, and that an API outage affects the phrasing rather
than the numbers.

---

## 3. Core algorithm: cash-flow forecasting

`app/tools/forecast.py`. The forecaster is rule-based and deterministic, not a learned
model. Every euro can be traced to a named component, which is what makes the output
defensible to a seller and auditable by a reviewer.

### 3.1 Projected sales

```
sales(d) = weekday_baseline[weekday(d)] × growth^(days_ahead / 28) × seasonality(month)
```

- **Weekday baseline:** mean gross sales per weekday over a 56-day window. The window
  is de-seasonalised first, so seasonality isn't applied twice.
- **Growth:** the trailing 28 days against the prior 28, **clamped to [0.80, 1.30]** so
  a single good fortnight can't run away.
- **Seasonality:** documented monthly factors, damped per category (`config.SEASONALITY`).

### 3.2 Payout releases

A pipeline of net accrual per sale date is maintained. On each scheduled payout date,
the platform releases everything sold on or before `payout_date − hold_days`:

```
payout       = released × (1 − reserve_pct) + reserve_held_from_previous_payout
reserve_held = released × reserve_pct
```

The rolling reserve is modelled as **rolling**: it is withheld on one payout and
released on the next. If you treat it as a permanent deduction, every seller looks
insolvent. We caught this during development because the unit economics stopped
reconciling (`test_rolling_reserve_does_not_leak_cash`).

The pipeline starts from **actual history** (`payout_state()` replays the schedule
over the real ledger), not from state written by the data generator. This is what
lets the forecaster start from any date, and therefore what makes it backtestable.

### 3.3 Outflows

- **Variable costs:** COGS, shipping and advertising, as a measured share of sales.
- **Pre-bought stock:** when a scheduled bill buys stock (`inventory_value`), that stock
  covers per-order product costs until it runs out, so the same goods are never paid
  for twice. The goods arrive on the originally agreed date: negotiating to *pay*
  later doesn't delay the *delivery*. An earlier version charged for stock twice, and
  that turned a timing problem into what looked like a permanent loss.
- **Recurring fixed costs:** payments that repeat on a stable schedule, detected from
  history (at least 3 occurrences, with the gaps between them varying by 4 days or
  less). This includes loan repayments, which appear in the ledger of every seller
  who declares debt service.
- **Scheduled obligations:** future bills the seller has declared.

### 3.4 Risk findings

The daily walk produces the balance path, and from it: the lowest point and its date,
the first date the balance goes negative, the amount needed to stay above the safety
buffer, **how long** the money is needed (`suggested_bridge_days`), and **how long
there is to arrange it** (`days_until_first_shortfall`).

**These two time quantities are different, and mixing them up is a real bug.** An
early version used "days needed" as the deadline for arranging finance, which ranked a
1-day merchant cash advance above a microloan costing a fraction as much. They are now
separate inputs to the financing engine.

**Driver attribution** adds up everything paid from today to the lowest point, instead
of looking only at a fixed window before it. The payment that causes a low point often
lands well before the low point itself.

### 3.5 Scenario support

`forecast_cashflow(ctx, horizon, scenario)` also takes an optional `Scenario`: bills
moved or split, ad spend cut, sales changed, payouts delayed, a new monthly cost, or
financing inflows and repayments. `Scenario()` with no changes reproduces the baseline
exactly (`test_empty_scenario_reproduces_the_baseline_exactly`).

### 3.6 Measured accuracy

There are two measurements, because either one alone would mislead.

**Consistency check.** `backtest()` forecasts from a past date and compares the result
with the actual ledger. Across 4 sellers and 30/45/60-day horizons, the mean absolute
error is **3.1%** of monthly revenue, and the worst case is **6.5%**. But the ledger was
generated by the same process the forecaster assumes: the same seasonality and the
same payout schedule. So this shows the model behaves as designed. **It is not
evidence of real-world accuracy**, and we don't present it as such.

**Stress test.** `scripts/stress_test.py` regenerates the sandbox with assumptions the
forecaster doesn't know, then backtests again:

| Scenario | Mean error | Worst |
|---|---:|---:|
| Same process the forecaster assumes | 3.1% | 6.5% |
| Daily sales twice as noisy | 4.4% | 9.5% |
| A seasonal pattern the forecaster doesn't know | 8.3% | 16.8% |
| Marketplace payouts arrive 0-3 days late at random | 19.4% | 47.9% |
| All three at once | 26.6% | 46.4% |

Late payouts are by far the largest sensitivity. One delayed payout moves an entire
payment across the date being measured. This is the method's main weakness, and it is
the reason the what-if simulator has a *payouts arrive late* setting (section 6):
sellers can test it on their own projection instead of trusting a single number.

The error is measured against **monthly revenue**, not the closing balance. Measuring
against the balance flatters sellers with large balances and punishes small ones.

Unforecastable payments are reported separately, not absorbed into the error. For
Amara, a 30-day backtest has a raw error of EUR 4,921, of which EUR 4,500 is a single
supplier deposit that was never declared. **A rule-based forecaster can't see a lumpy
commitment that nobody told it about.** That is why the product asks sellers to
declare their upcoming bills.

---

## 4. Core algorithm: financing matching

`app/tools/financing.py`. A transparent rule engine, not a learned scorer.

### 4.1 Per-criterion evaluation

A product is never "a 72% match". Every criterion produces a complete, checkable row:
what was required, the seller's actual value, and the verdict. A product is eligible
only if **every** criterion passes. Products that fail one or two criteria are
reported as **near-misses**, with the gap measured and, where it can be known, what
would fix it.

### 4.2 True cost of capital

Two figures are returned:

- `total_cost`: the cost over the product's own natural term.
- `cost_for_period`: the cost of holding the money for the days actually needed.

| Structure | `cost_for_period` | Rationale |
|---|---|---|
| Revolving / overdraft | `amount × apr × days/365` | Interest is charged only on what is drawn |
| Factoring / trade credit | `amount × fee_30 × days/30` | Priced per 30 days outstanding |
| Committed term loan | full-term cost | You commit to the whole facility |
| Revenue share | full cost | A fixed factor rate can't be reduced by repaying early |
| Grant | 0, with co-funding disclosed | Non-repayable, and excluded for working capital |

### 4.3 Ranking and timing

The ranking sorts by `(too_slow, cost_for_period, speed_days)`, where
`too_slow = speed_days > days_until_needed`. A slow product is flagged and kept, not
hidden: it simply can't be the first line of defence this time.

### 4.4 Verification by simulation

Before anything is recommended, `verify_financing_options()` runs every candidate that
can arrive in time through the what-if simulator. The simulation uses the date the
money actually arrives and the product's real repayment schedule. Only products that
keep the seller out of the red are recommended. This caught a real flaw: ranking by
cost alone had recommended a product whose monthly repayments opened a new shortfall
the following month.

The expensive fast option is kept in the catalog on purpose, so the copilot can show
what it really costs. For Amara, the merchant cash advance costs EUR 1,844, against
EUR 218 for the recommended bridge, and even then it doesn't keep her out of the red.

---

## 5. Business analysis

`app/tools/analysis.py`.

```
contribution_margin   = 1 − (variable costs + platform fees + refunds) / sales
monthly_cash_surplus  = revenue × contribution_margin − regular monthly payments
breakeven_revenue     = regular monthly payments / contribution_margin
cash_trapped_days     = platform_balance / daily sales
```

`monthly_cash_surplus` is **cash left over after all regular payments, including loan
repayments**. It is deliberately *not* called profit, because repaying a loan's
principal is a cash outflow but not an accounting expense. Peer comparison uses
p25/median/p75 bands from `data/benchmarks.json`, which are **synthetic and labelled
as such in every response**.

---

## 6. What-if simulator

`app/tools/whatif.py`. It runs the baseline and a changed scenario side by side, then
explains the difference. It is a T1 tool: it projects, and it never changes anything.

A seller can pay a bill later or split it, cut ad spend (optionally assuming some lost
sales), change sales across the period, delay every payout, add a new monthly cost, or
take a specific financing product. It works from the web panel, or in plain English
through the agent ("what if I pay the supplier 3 weeks late?").

Three honesty rules are built in:

1. **Money can't arrive before the product can be arranged.** Financing lands on
   `today + speed_days`, with its real repayment schedule.
2. **Only products the seller actually qualifies for can be simulated.** Anything else
   is refused, with the criteria that failed.
3. **Assumptions are stated.** Cutting ads loses no sales unless the seller says so,
   and the reply says that plainly. When sales fall, the reply also explains a
   counter-intuitive effect: the low point can briefly look better, because fewer
   orders means paying less right now while the lost income arrives later as smaller
   payouts. Such a scenario should be judged on the ending balance.

Every result uses one vocabulary, judged against the same safety buffer the financing
matcher uses, so the two tools can't disagree: *fixes*, *avoids negative*, *improves*,
*no effect*, *worsens*, *breaks* (`test_matcher_and_simulator_agree_on_timing`).

---

## 7. Security design

Full self-assessment and known-risk list: **[SECURITY.md](SECURITY.md)**.

| Tier | Scope | Enforcement |
|---|---|---|
| `T0_READ` | Read simulated data | Registry lookup |
| `T1_RECOMMEND` | Analysis, forecasts, matches, alerts, what-ifs. No side effects | **Session default**, in the API and the UI |
| `T2_ACTION` | Real-world consequences | Staged only; human confirmation required |

A T2 call doesn't act. It returns a `pending_confirmation` token that is
server-generated, single-use, expires after 600 seconds, and is bound to a SHA-256
hash of the exact details the user was shown. `confirm_action` is **not in the agent's
tool registry**, so a fully prompt-injected model has no way to approve its own
action. Confirmation decisions are audited inside `confirm_action` itself, so no code
path can execute an action without recording the decision.

**Prompt injection.** The threat that matters here is *indirect* injection through
fields the seller doesn't control, and the sandbox contains a real planted attack.
Detection covers English, Chinese, Arabic, German, French and Spanish. It also undoes
simple disguises (full-width letters, zero-width characters, and letters split apart
like "I-g-n-o-r-e"). False positives are tested in the same six languages. Pattern
matching raises the cost of an attack but doesn't solve it. The permission model is
what bounds the damage.

**Audit log.** An append-only log in which each record holds the SHA-256 of the one
before it, and `verify_chain()` detects edits and deletions. **Each session can read
only its own records.** The full log contains every seller's activity, so exposing it
on request would leak one seller's financial questions to another.

---

## 8. Keeping the system, the documents and the deck consistent

The numbers quoted in documents drift from the system unless something forces them
to match. That already happened once in this project: the deck said one monthly
figure and the tool said another. So:

- `app/facts.py` computes every figure quoted outside the code.
- `scripts/generate_evidence.py` writes those figures to `docs/evidence/facts.json`.
- `scripts/build_deck.js` reads every number in the deck from `facts.json`, and no
  euro amount is typed into the deck by hand.
- `tests/test_consistency.py` checks that `facts.json` matches the live system, that
  each document quotes the live figures, that previously published wrong figures
  never reappear, and that the data doesn't contradict itself (declared loan
  repayments exist in the ledger, claimed deposits were actually paid, stock purchases
  are marked as stock).

A stale number is a failing test.

---

## 9. Reproducibility

Everything is deterministic: fixed seeds, a pinned `as_of = 2026-09-10`, and no sampling
in offline mode.

```bash
python scripts/generate_data.py       # 4 sellers, 4,794 transactions
python scripts/generate_evidence.py   # 18 scenarios, 79 audit records, stress test, facts.json
pytest -q                             # 200 tests
```

## 10. Known limitations

These are covered briefly here and expanded in [SECURITY.md](SECURITY.md).

1. **Late payouts and undeclared one-off bills** are the largest sources of forecast
   error (see the stress test). The what-if simulator exposes the first, and declaring
   bills addresses the second. Neither is solved.
2. **Rule-based forecasting can't anticipate structural breaks**, such as a
   marketplace changing its terms or a supplier failing.
3. **Eligibility matching is not underwriting.**
4. **Synthetic benchmarks and a synthetic catalog.**
5. **Pattern-based injection defence is incomplete by nature.**
6. **Demo-grade sessions**, with no user authentication.
7. **LLM mode hasn't been exercised against the live API** in this sandbox.
