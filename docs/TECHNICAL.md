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
- **Growth:** the trailing 28 days against the prior 28, measured on the same
  de-seasonalised sales as the baseline, and **clamped to [0.80, 1.30]** so a single
  good fortnight can't run away. Until the finals branch, growth was measured on raw
  sales, which counted the seasonal step twice (risk R12 in SECURITY.md, now fixed;
  `tests/test_seasonality_growth.py`).
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
  less). A bill paid about once a month is projected on its usual day of the month
  ("rent on the 1st"), not every 30 or 31 days, which made it drift. This includes loan repayments, which appear in the ledger of every seller
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
lands well before the low point itself. Each driver carries the number of payments it
adds up, so three rent payments are never reported as one.

**Payout timing as a named cause.** The forecast also walks the second ledger forward:
`payout_queue` is the money already earned and not yet paid out, starting from the real
platform balance and moving with projected net sales and payouts. `findings.payout_hold`
reports how much of it the marketplace is holding on the day of the lowest point, and
the headline alert says so in one sentence. The bills decide when the balance is
lowest; the payout hold is why the seller's own earnings are not there to meet them.

**Bills due today or overdue.** A declared bill due on or before the forecast date is
charged on the first day and marked overdue, unless the bank ledger already shows it
as paid.

### 3.5 Scenario support

`forecast_cashflow(ctx, horizon, scenario)` also takes an optional `Scenario`: bills
moved or split, ad spend cut, sales changed, payouts delayed, a new monthly cost, or
financing inflows and repayments. `Scenario()` with no changes reproduces the baseline
exactly (`test_empty_scenario_reproduces_the_baseline_exactly`).

### 3.6 Measured accuracy

There are two measurements, because either one alone would mislead.

**Consistency check.** `backtest()` forecasts from a past date and compares the result
with the actual ledger. Across 4 sellers and 30/45/60-day horizons, the mean absolute
error is **1.5%** of monthly revenue, and the worst case is **3.0%**. But the ledger was
generated by the same process the forecaster assumes: the same seasonality and the
same payout schedule. So this shows the model behaves as designed. **It is not
evidence of real-world accuracy**, and we don't present it as such.

**Stress test.** `scripts/stress_test.py` regenerates the sandbox with assumptions the
forecaster doesn't know, then backtests again:

| Scenario | Mean error | Worst |
|---|---:|---:|
| Same process the forecaster assumes | 1.5% | 3.0% |
| Daily sales twice as noisy | 3.3% | 5.9% |
| A seasonal pattern the forecaster doesn't know | 7.6% | 13.4% |
| Marketplace payouts arrive 0-3 days late at random | 9.5% | 42.5% |
| All three at once | 14.8% | 42.1% |

Late payouts are by far the largest sensitivity. The first three rows are one run of
12 backtests each. The two late-payout rows are 1,200 backtests each: the run is
repeated over 100 independent sets of random delays, because a single set is a coin
flip on whether a whole payout crosses a measured date.

How a late payout is modelled: it releases exactly the sales it was scheduled to
release and reaches the bank 0-3 days later. A payout pushed past the end of the
history is still pending, and its money stays in the platform balance. Each seller has
its own seeded random generator (`tests/test_stress_harness.py`). The harness submitted
in October deleted any payout scheduled within 3 days of the end of the history and
shared one generator across sellers; it reported 19.4% and 47.9% for this row.

The late-payout error is concentrated, not spread evenly:

| Late-payout backtests | Count | Mean error | Worst |
|---|---:|---:|---:|
| No payout in transit on either date | 690 | 1.4% | 3.0% |
| A payout was in transit on the day the forecast was made | 273 | 2.1% | 3.4% |
| A payout was in transit on the day the forecast was measured | 237 | 41.5% | 42.5% |
| All (median 2.2%, 90th percentile 41.0%) | 1,200 | 9.5% | 42.5% |

"In transit" means due on the schedule but not yet in the bank. The second row used to
average 27.1% when it was first measured: the forecaster worked out which payouts had been paid from the schedule
alone, so a payout that was late on the day of the forecast was assumed paid and never
counted. `payouts_in_transit()` now compares the schedule with the payouts actually in
the bank ledger and expects any that are missing on the first forecast day
(`test_late_payout_is_expected_instead_of_forgotten`). That change took the late-payout
mean from 15.2% to 9.5%.

The third row cannot be fixed by a single-path forecast: the money really does arrive
after the measured date. Its 237-in-1,200 share is specific to this sandbox: four
sellers, one measured date, and one seller (TechFix) with a payout scheduled on exactly
that date. The split is the finding that carries over: the forecast is as good as the
baseline unless a payout slips across the day you care about, and then it is wrong by
about one payout. This is the method's main weakness,
and it is the reason the what-if simulator has a *payouts arrive late* setting
(section 6): sellers can test it on their own projection instead of trusting a single
number.

**What the consistency check does not show.** Five limits, stated so nobody has to
find them:

1. **It compares one number**: the bank balance on the last day of the window. It does
   not check the lowest point, the date of the lowest point or the bridge amount, which
   are the figures a seller acts on.
2. **No backtest window contains a declared bill.** Every window ends on 10 September,
   and the first declared bill is due on 25 September. The situation the product exists
   for, a large bill meeting the payout schedule, is not back-tested.
3. **The headline figure leaves out one-off payments nobody declared.** Before that
   adjustment the mean error is **13.2%** of monthly revenue (worst case 59.7%), and
   the adjustment removes 80.5% of the raw error. All of it is two payments in Amara's
   ledger: a EUR 4,500 stock deposit on 20 August and a EUR 1,850 VAT prepayment on
   15 July. For Amara, a 30-day backtest has a raw error of EUR 4,827, of which
   EUR 4,500 is that deposit. Neither payment was on the declared-bills list when the
   forecast was made, but a real seller would have known about both. So the headline
   figure means "accuracy when the seller declares the bills they know about". **A
   rule-based forecaster can't see a lumpy commitment that nobody told it about**,
   which is why the product asks sellers to declare upcoming bills.
4. **The error is divided by monthly revenue, not by the closing balance.** Measuring
   against the balance flatters sellers with large balances and punishes small ones.
   Divided by the closing balance, the mean error is **3.8%**.
5. **The seasonal factors in `config.SEASONALITY` are the same ones the data generator
   uses.** For seasonality the check is circular. The "seasonal pattern the forecaster
   doesn't know" row of the stress test is the measure of that exposure.

### 3.7 Real-data check of the sales forecast

Everything above is measured on data we generated. To break that circle for at least
one component, `scripts/uci_backtest.py` runs the sales projection, unchanged and
untuned, on a real retailer: the UCI *Online Retail II* dataset (a UK online gift-ware
seller, 1 December 2009 to 9 December 2011, 1,067,371 invoice lines; Chen, D., 2012,
https://doi.org/10.24432/C5CG6D, licence CC BY 4.0). After cleaning (cancellations, non-positive quantities and prices and
non-product codes removed) 1,036,877 lines remain, added up into 739 calendar days,
135 of them with no sales.

**Scope: sales only.** The dataset has no payouts, fees, bills or bank balances, so
this does not test the payout model, which is the part of the product that matters
most.

Method: one forecast every 7 days (80 forecast dates), each seeing only the days up to
its date and scored on the next 14, 30 and 60 days. Nothing is fitted to this dataset.
The error is the gap between forecast and actual total sales over the horizon, as a
share of actual sales, averaged over forecast dates (median in brackets).

| Horizon | Our forecast | Repeat last week | Weekday average, 8 weeks | Same weekday last year* |
|---|---:|---:|---:|---:|
| 14 days | 32.6% (13.3%) | 35.3% (19.4%) | 36.7% (14.0%) | 15.0% (10.8%) |
| 30 days | 18.7% (10.5%) | 27.8% (16.2%) | 24.2% (11.0%) | 10.6% (10.9%) |
| 60 days | 19.1% (11.8%) | 29.6% (20.7%) | 25.9% (14.5%) | 7.4% (7.4%) |

\* Needs a year of history, so it covers only the last 45 of the 80 forecast dates.
On those same 45 dates our forecast's 60-day error is 24.6% (15.0%).

What this shows, plainly:

- The forecast **beats the two naive forecasts that use only recent weeks** at 30 and
  60 days, and is roughly level with them at 14 days.
- It **loses clearly to "same weekday last year"** wherever a year of history exists.
  The monthly seasonal table was written for the sandbox and under-states this
  retailer's Christmas peak; the seller's own previous year is a far better guide.
  Using it when it exists is the obvious next improvement.
- The averages are pulled up by the Christmas shutdown: the retailer closes from
  24 December to early January and the forecaster knows nothing about holidays. The
  worst single 14-day forecast (made on 22 December 2010) predicted GBP 639,108
  against GBP 58,495 of actual sales.

The download script is `scripts/uci_download.py`; the raw data is not in the
repository (`data/external/` is git-ignored). Results: `docs/evidence/uci_backtest.json`.

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
what it really costs. For Amara, the merchant cash advance costs EUR 1,835, against
EUR 217 for the recommended bridge, and even then it doesn't keep her out of the red.

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
pytest -q                             # 367 tests
```

## 10. Known limitations

These are covered briefly here and expanded in [SECURITY.md](SECURITY.md).

1. **Late payouts and undeclared one-off bills** are the largest sources of forecast
   error (see the stress test). The what-if simulator exposes the first, and declaring
   bills addresses the second. Neither is solved.
   - **Quarterly and annual bills are not detected.** The detector needs three payments
     inside 180 days, so VAT prepayments and insurance must be declared by the seller.
   - **Stock already owned on the forecast date is not an input.** Stock is only
     counted when it arrives with a declared bill. A seller holding unsold stock would
     see product costs charged that they have already paid.
   - **Refund and chargeback rates are simple 56-day averages.** Refunds lag sales by
     days and chargebacks by weeks, so the measured rates are approximate (for Amara
     the 56-day chargeback rate is 0.68% against 0.42% over the whole history), and
     chargebacks are charged on the day of sale.
2. **Rule-based forecasting can't anticipate structural breaks**, such as a
   marketplace changing its terms or a supplier failing.
3. **Eligibility matching is not underwriting.**
4. **Synthetic benchmarks and a synthetic catalog.**
5. **Pattern-based injection defence is incomplete by nature.**
6. **Demo-grade sessions**, with no user authentication.
7. **LLM mode is exercised live but not by the test suite.** It was run against the
   live API on 18 October 2026 (risk R11 in SECURITY.md); the tests and the evidence
   pack always run offline.
