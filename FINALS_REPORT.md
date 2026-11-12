# Finals report - SME Finance Copilot (Team Finova)

Working branch: `finals`. The submitted version is commit `537c0d8` and is untouched.
The repository's default branch is called `master`, not `main`; the pull request
targets `master`.

All commands were run from the repository root with the project's virtual environment
(`.venv/bin/python`). "Monthly revenue" means the seller's average monthly revenue over
the previous 90 days. Every number below came from a command run in these sessions
(11-12 November 2026); the command is named next to it.

How to pick this up later: read this file, run `git log --oneline`, then
`pip install -r requirements-dev.txt && pytest -q` (expect 367 passed).

---

## 1. Summary

1. Fixed 12 defects with regression tests: the seasonality double-count (R12), the broken stress-test tool, and audit items A2, A3, A5, B2, B4, B6, B10 plus one new one (N1). A4 turned out to be a labelling gap and is now explained in the product.
2. Amara's story barely moved: lowest balance -EUR 5,084 -> -EUR 5,055, amount needed EUR 6,584 -> EUR 6,555, still 47 days, same dates, same recommended product. New: the product now says EUR 8,459 of her own money is in the payout queue on her lowest day.
3. The accuracy numbers improved and are now honestly caveated: consistency check 3.1% -> 1.5%; late-payout stress test 19.4% -> 9.5% (1,200 runs, not 12); and a first real-data test (UCI) where the sales forecast beats "repeat last week" but loses to "same week last year".
4. Still open: 10 smaller findings from the fresh review wait for approval (section 5), most importantly the narrow output guardrail (N6) and the missing time-out in LLM mode (N4). The deck is not edited (section 7), and the recorded live-LLM transcript predates the fixes.
5. Tests: 232 -> 367, all passing.

---

## 2. Before / after table

"Before" = submitted version, regenerated in a temporary folder:
`git archive 537c0d8 | tar -x -C <tmp>`, then `python scripts/generate_evidence.py` there.
It reproduced the committed `docs/evidence/` exactly, apart from `audit_log.jsonl`
(timestamps and random ids differ on every run).

"After" = `finals` at commit `4da9784`: `python scripts/generate_evidence.py`, then read
`docs/evidence/facts.json`, `backtest_results.json`, `stress_test.json`.
UCI rows: `python scripts/uci_download.py` then `python scripts/uci_backtest.py`.

| Number | Before | After | Where it appears |
|---|---:|---:|---|
| Tests passing (`pytest -q`) | 232 | 367 | README, TECHNICAL, SECURITY, facts.json, deck |
| Consistency check, mean error (% of monthly revenue) | 3.1% | 1.5% | README, TECHNICAL 3.6, SECURITY R1, scenarios.md, deck |
| Consistency check, worst case | 6.5% | 3.0% | same |
| Same check without the one-off adjustment | not reported | 13.2% mean, 59.7% worst | TECHNICAL 3.6 (new disclosure) |
| Same check divided by closing balance | not reported | 3.8% | TECHNICAL 3.6 (new disclosure) |
| Stress: payouts 0-3 days late, mean | 19.4% | 9.5% | README, TECHNICAL 3.6, SECURITY R1, deck |
| Stress: payouts late, median | not reported | 2.2% | README, TECHNICAL 3.6, SECURITY R1 |
| Stress: payouts late, worst | 47.9% | 42.5% | README, TECHNICAL 3.6 |
| Stress: payouts late, number of backtests | 12 | 1,200 | TECHNICAL 3.6 |
| Stress: noisier sales, mean / worst | 4.4% / 9.5% | 3.3% / 5.9% | TECHNICAL 3.6 |
| Stress: unknown seasonality, mean / worst | 8.3% / 16.8% | 7.6% / 13.4% | TECHNICAL 3.6 |
| Stress: all three, mean / worst | 26.6% / 46.4% | 14.8% / 42.1% | TECHNICAL 3.6 |
| Amara: growth factor per 28 days | 1.0376 | 1.0150 | forecast assumptions, UI |
| Amara: first day below the EUR 1,500 buffer | 16 Sep | 16 Sep | alerts |
| Amara: first day below zero | 25 Sep | 25 Sep | README, deck |
| Amara: lowest balance | -EUR 5,084 on 4 Oct | -EUR 5,055 on 4 Oct | README, scenarios.md, deck |
| Amara: amount needed (bridge) | EUR 6,584 | EUR 6,555 | README, scenarios.md, deck |
| Amara: bridge days (first dip to last day below buffer) | 47 | 47 | README, scenarios.md, deck |
| Amara: days actually below the buffer | 43 | 43 | alert, reply, UI (now explained) |
| Amara: days to arrange it | 6 | 6 | README, deck |
| Amara: her own money in the payout queue on 4 Oct | not reported | EUR 8,459 | README, alert, reply, UI, facts.json (new) |
| Amara: balance on day 60 | EUR 2,815 | EUR 2,671 | facts.json, deck |
| Recommended product and cost | Ember Seasonal Bridge, EUR 218 | same, EUR 217 | README, TECHNICAL 4.4, deck |
| Cheapest product overall (too slow) | Granary Supplier Payment Terms, EUR 196 | same, EUR 195 | README, deck |
| Merchant cash advance cost | EUR 1,844 | EUR 1,835 | TECHNICAL 4.4, deck |
| Amara 30-day backtest, raw error | EUR 4,921 | EUR 4,827 | TECHNICAL 3.6, SECURITY R1 |
| What-if "pay supplier 3 weeks later", low point | -EUR 3,925 | -EUR 4,081 | scenarios.md, deck |
| What-if "payouts 3 days late", low point | -EUR 5,412 | -EUR 5,378 | scenarios.md, deck |
| What-if "take Ember", low point | EUR 959 | EUR 780 | scenarios.md, deck |
| What-if "take SwiftCash", low point | -EUR 796 | -EUR 927 | scenarios.md, deck |
| Real-data check (UCI), 60-day sales total error | none | ours 19.1%; repeat last week 29.6%; same weekday last year 7.4% | README, TECHNICAL 3.7, uci_backtest.json |

Unchanged: monthly revenue EUR 10,991, monthly surplus EUR 620, bank EUR 3,180, payout
queue today EUR 5,007, 13.7 days of sales trapped, Lina's figures, 12 known risks,
18 scenarios, 79 audit records, 4,794 transactions.

### Why each number moved, in plain words

- **Growth factor (1.0376 -> 1.0150), fix B1.** The old code compared the last 28 days of sales with the 28 days before without removing the calendar effect. September is a stronger month than August in the seasonal table (1.04 against 0.90), so part of the "growth" was just the calendar. With that removed, measured growth is lower.
- **Lowest balance and bridge amount (EUR 30 better), fix B1.** Slightly lower projected sales mean slightly lower product, shipping and ad costs before the low point, while the payouts arriving before 4 October come mostly from sales already made. No other fix moved these two numbers.
- **Balance on day 60 (EUR 144 lower), fix B1.** Lower projected sales over two months means less money arriving later.
- **Financing costs (EUR 1 to EUR 9 lower).** They are calculated on the bridge amount, which is EUR 30 smaller. The recommendation is unchanged.
- **What-if low points with a product or a late supplier payment (EUR 180 worse), fix B2.** Rent now lands on the 1st and wages on the 30th, not one day later, so one more bill falls before those scenarios' low points. The baseline low point (4 October) is not affected.
- **Consistency check (3.1% -> 2.7% -> 1.5%; worst 6.5% -> 3.0%).** The first step is B1. The larger step is B2: bills were projected every 30 or 31 days, so in some backtests a loan repayment was counted one day early and landed inside the window when the real one fell just outside it. TechFix's 60-day error went from EUR -2,596 to EUR -816 for that reason.
- **Late-payout stress test (19.4% -> 15.2% -> 9.5%).** First step: the test tool itself was wrong (section 3). Second step: fix N1, the forecaster now notices a payout that is due but not yet in the bank.

---

## 3. Stress test: what was wrong, what changed, and the sentence to use

### Was it ever fixed before this work? No.

`git log --follow scripts/stress_test.py` shows one commit only (`6bd8a50`, 22 September).
Running the old logic and counting payouts showed TechFix going from 14 payouts to 13,
with EUR 9,669 -> EUR 26,786 left in its platform balance. TechFix has a payout scheduled
on 10 September, the last day of the history, and the old tool deleted it (about
EUR 17,000) in every run, whatever the random draw. All three TechFix backtests then
showed errors of 43-48% (old tool logic, run on the code after the seasonality fix).
That is 3 of the 12 backtests and the source of the old worst case. The old tool also
used one random generator for all four sellers and moved each payout's sales window
together with its date.

### What the tool does now (`d0cae72`, tests in `tests/test_stress_harness.py`)

- A late payout releases exactly the sales it was scheduled to release and lands 0-3 days later.
- If that pushes it past the end of the history it is still pending, and its money stays in the platform balance. Tests check this euro for euro.
- One seeded random generator per seller.
- One set of random delays is a coin flip, so the late-payout rows are repeated over 100 sets (1,200 backtests each).
- The committed dataset is unchanged, byte for byte (checked with `cmp`, and by a test).

### Result

Command: `python scripts/stress_test.py` (about 13 seconds). Error as % of monthly revenue.

| Scenario | Mean | Worst | Backtests |
|---|---:|---:|---:|
| Same process the forecaster assumes | 1.5% | 3.0% | 12 |
| Daily sales twice as noisy | 3.3% | 5.9% | 12 |
| A seasonal pattern the forecaster doesn't know | 7.6% | 13.4% | 12 |
| Payouts 0-3 days late at random | 9.5% (median 2.2%) | 42.5% | 1,200 |
| All three at once | 14.8% | 42.1% | 1,200 |

The late-payout error is not spread evenly (`by_payout_position` in `stress_test.json`):

| Late-payout backtests | Count | Mean error | Worst |
|---|---:|---:|---:|
| No payout in transit on either date | 690 | 1.4% | 3.0% |
| A payout was late on the day the forecast was made | 273 | 2.1% | 3.4% |
| A payout was late on the day the forecast was measured | 237 | 41.5% | 42.5% |

The middle row averaged 27.1% when first measured. That was a product weakness, now
fixed (N1, `1d0bcd4`): the forecaster assumed every scheduled payout had been paid. It
now compares the schedule with the payouts actually in the bank ledger.

Two honest caveats:
- The last row cannot be fixed by a single-line forecast: the money really does arrive after the measured date.
- Its share (237 of 1,200) is specific to this sandbox: every backtest is measured on 10 September and TechFix has a payout due on exactly that day. The split is the finding that carries over, not the 9.5% average: the forecast is as good as the baseline unless a payout slips across the day you care about, and then it is wrong by about one payout.

### Wording decision

The tool is fixed and re-measured, so the figure can be quoted with its method.

**Deck (short):**
> Late payouts are our biggest forecast risk: when payouts slip 0-3 days, the average error rises from 1.5% to 9.5% of monthly revenue (1,200 simulated backtests).

**Docs (already in README, TECHNICAL.md and SECURITY.md in this form):**
> When marketplace payouts arrive 0-3 days late at random, the mean error rises to 9.5% (median 2.2%, worst case 42.5%, over 1,200 backtests with 100 sets of random delays). When a payout is due on the very day the forecast is measured and arrives late, the error averages 41.5%; when no payout is in transit it averages 1.4%.

**If a judge asks why it changed from 19.4%:** "Our own review found the test tool deleted some late payouts instead of delaying them. We fixed the tool, tested it, ran it 100 times instead of once, and then fixed a real weakness it exposed."

Do not say 19.4% or 47.9% any more, except as "what we reported at submission".

### The same family of bug in the product (audit B6): fixed in `32afce8`

In the "payouts arrive late" what-if, a payout pushed past the last forecast day was
left out and the reply compared ending balances as if the money were gone (Amara, 53
days, 3-day delay: ending balance "EUR 3,441 becomes -EUR 1,741"). The forecast now
lists such payouts as pending, and the reply adds: "That ending balance leaves out
EUR 5,183 of delayed payouts that land just after the last day shown ... The money is
late, not lost: counting it, the ending balance would be EUR 3,441."

---

## 4. Audit status table

| Item | Status | Evidence | Demo severity before the fix | Fixed in |
|---|---|---|---|---|
| B1 seasonality double-count (R12) | **Fixed** | Test seller with no real growth, November start: growth 1.1964 -> 1.0000; sales error at day 60 +46.9% -> 0.0%, at day 180 +216.7% -> 0.0%. January start: 0.80 (floor) -> 1.0000; -38.0% / -76.2% -> 0.0%. 18 tests in `test_seasonality_growth.py`, all failing before | High for any winter date | `f0196c0` |
| Stress-test tool (Step 2) | **Fixed** | Section 3. 14 tests in `test_stress_harness.py` | High (headline figure was wrong) | `d0cae72` |
| A1 early payout picked a payout after the shortfall | **Already fixed** before this work | `alerts.py` only offers a payout dated after the first dip; existing tests pass for all 4 sellers. Amara: dip 16 Sep, payout offered 21 Sep | - | before `537c0d8` |
| A2 bill due today or overdue was dropped | **Fixed** | Before: a EUR 2,000 bill due on 10 Sep or 7 Sep changed nothing. Now it is charged on day one and marked overdue, unless the bank ledger shows it paid | Medium | `cde4ba7` |
| A3 "one payment" could be several added up | **Fixed** | Drivers carry a payment count; the alert says "3 payments to X ... in total". Not visible with the demo sellers (top driver was a single bill in all 20 seller x horizon cases) | Low | `5c1962f` |
| A4 47 bridge days vs 43 days below buffer | **Not a bug - labelling, now explained** | 47 = first dip (16 Sep) to last day below (1 Nov); 43 = days actually below (above the buffer on 21-24 Sep). A bridge cannot be handed back for 4 days, so 47 is the right financing length and is what `match_financing` receives. Alert, reply and UI now state both | Low | `04b9b35` |
| A5 payout timing could never be named as a cause | **Fixed** | The forecast now tracks the payout queue day by day. Amara: EUR 8,459 of her own earnings held on 4 October, more than the EUR 6,555 gap. In the headline alert, the reply, the UI and facts.json | **High** (it is the thesis) | `a1287f2` |
| B2 monthly bills drifted | **Fixed** | Rent was projected on 2 Oct, 2 Nov, 3 Dec, 3 Jan, 3 Feb, 6 Mar; now the 1st of every month. Consistency check 2.7% -> 1.5% | Medium | `c080fc5` |
| B3 quarterly and annual bills are not detected | **Still present, disclosed** | Three quarterly payments are not detected (the rule needs 3 inside 180 days). Now listed in TECHNICAL.md section 10 | Low | disclosed in `6932410` |
| B4 baseline averaged ledger rows, not days | **Fixed** | Same sales as 4 order rows a day: 60-day projected sales EUR 26,549 -> EUR 6,637 before; identical now. Sandbox figures unchanged | None in demo; needed for Step 5 | `6932410` |
| B5 no input for stock already owned | **Limitation, disclosed** | Not triggered by any demo seller (product cost is paid per order; future stock arrives with its bill) | None in demo | disclosed in `6932410` |
| B6 delayed payout past the horizon disappeared | **Fixed** | Section 3 | Medium (reachable in the web panel) | `32afce8` |
| B7 refund and chargeback rates are rough | **Still present, disclosed** | Amara: the sandbox marketplace deducts 4.10% for refunds; the forecaster measures 3.27% (56 days). Chargebacks 0.68% (56 days) vs 0.42% (whole history), charged on the day of sale | Low | disclosed in `6932410` |
| B8 what-if bill changes match by name only | **Still present** (not on the approved list) | Two bills from one supplier: delaying one by name moves both. No demo seller has two | Low | - |
| B9 "days of sales trapped" mixes net and gross | **Still present** (team decision pending) | Amara: 13.7 days as shown; 16.3 like for like. The payout-queue alert only fires when there is already a gap | Low-medium | - |
| B10 "for roughly None days" | **Fixed** | Only reachable with a negative safety buffer; guarded and tested for every seller and horizon | Low | `3ad4669` |
| N1 (new) payouts assumed paid from the schedule | **Fixed** | Section 3: that error group fell from 27.1% to 2.1% | Medium | `1d0bcd4` |

### Tier 3 - how strong is the accuracy evidence?

All of these are now written into TECHNICAL.md section 3.6, and the figures are checked
by `test_consistency.py`.

| Weakness | Measured | Disclosed before | Disclosed now |
|---|---|---|---|
| Only the last day's balance is compared, not the lowest point, its date or the bridge amount | by reading `backtest()` | No | Yes |
| No backtest window contains a declared bill | windows end 10 Sep; first declared bill 25 Sep | No | Yes |
| The one-off adjustment removes most of the error | removes 80.5% of raw error; unadjusted mean 13.2%, worst 59.7% | Partly | Yes, with the figures |
| The adjustment excuses bills the seller knew about | Amara's stock deposit (EUR 4,500) and VAT prepayment (EUR 1,850) | No ("never declared") | Yes |
| Divided by monthly revenue, not balance | by balance: 3.8% | Yes, without the figure | Yes, with the figure |
| `config.SEASONALITY` copies the data generator's table | identical tables; not changed, as instructed | Yes | Yes, plus the real-data check |

Not solved, only disclosed: the first two rows. Suggestion 5 in section 8 addresses them.

---

## 5. New findings from the fresh review (Step 4)

Fixed on the spot (no behaviour risk):

| Finding | Evidence | Fixed in |
|---|---|---|
| In LLM mode the model could not see the findings of longer forecasts | Each tool result is cut to 20,000 characters and the day-by-day series came first. At 90 and 180 days the findings started at character 23,913 and 45,162 in the submitted version. Findings now come first; tested at 30/60/90/180 days for every seller | `c19ef5b` |
| TECHNICAL.md said LLM mode had never been run live; README and SECURITY R11 say it was (18 October) | text | `c19ef5b` |
| SECURITY.md said the output check blocks "any claim of approval" | it blocks three wordings (see N6); the document now says which | `c19ef5b` |
| `docs/evidence/llm_live_run.md` shows the old figures | labelled "recorded before the finals fixes"; a test requires the label or current figures | `2d9e298` |
| README told readers to run `pytest` after installing `requirements.txt`, which has no pytest | added `requirements-dev.txt`; dependency licences listed in the README | `4da9784` |
| A test banned the old figure "2.5%" by plain text match, which also matched the true new figure 42.5% | the test now matches whole figures only, with its own test | `c080fc5` |

Checked and found correct:
- No document, in-app text, deck slide or speaker note says when Amazon's reserve rule changed. Nothing to correct.
- Every test named in README, TECHNICAL.md and SECURITY.md exists.
- `.gitignore` covers `.env`; no `.env` exists, and none was created or read. A test now checks that neither `.env` nor `data/external/` is committed.
- Start-up: `import app.main` takes 0.46 s; the page is 38 KB with no external files.
- All four sellers, every GET route, horizons 7 to 180 days: no errors.

**Still present - need approval before fixing.** Effort: S = under an hour, M = half a day.

| # | Finding | Evidence | Demo severity | Effort | Recommendation |
|---|---|---|---|---|---|
| N6 | The output guardrail is narrower than the pitch says | "Your loan is approved.", "You are pre-approved for EUR 5,000", "I have submitted your application." and "Consider it done - funds are on the way" all pass `check_output`. Only "you are approved", "guaranteed / we guarantee" and "you will definitely get" are blocked. Slide 14 says an output guardrail enforces "never says approved" | **High** if a judge probes LLM mode | S | **Fix** (more wordings, with tests), or soften slide 14 |
| N4 | LLM mode has no time-out | The SDK default is a 600-second read time-out with 2 retries (`anthropic._constants`). On poor venue Wi-Fi a live turn could hang for minutes before the offline fallback starts | **High** in a live LLM demo | S | **Fix** (about 20 seconds, 1 retry) |
| N9 | LLM mode has no memory between turns | `/api/chat` never passes the conversation history to the model, so "and what if I take that one?" has no context | Medium | S-M | Fix, or script the demo as single questions |
| N2 | `/api/seller/{id}/whatif` returns a server error on malformed input | text where a number or an object is expected gives HTTP 500; a horizon of -5 or 1,000,000,000 is accepted and echoed back | Low (not reachable from the UI) | S | Fix |
| N3 | `/api/seller/{id}/financing` accepts nonsense | amount "NaN" gives HTTP 500; negative amounts are silently replaced by EUR 5,500 | Low | S | Fix |
| N7 | Growing sellers are projected slightly too low | the baseline is the 56-day average with growth applied from today, so it starts one growth step behind: a seller growing 3.5% per 28 days is under-projected by 3.7%, one growing 10% by 9.7% | Low (errs on the cautious side) | S, but **moves every number** | Disclose, do not fix before the final |
| N8 | The growth estimate is mostly noise | across every date from 1 May to 10 September, the estimate's spread is 2.8 to 5.9 points per seller, against true growth of 0.7 to 5.3% | Low | M | Disclose |
| N10 | Business analysis crashes for a seller with no sales at all | `TypeError` in `analyse_business` | None (every demo seller has sales) | S | Fix |
| N11 | `get_transactions` is in the permission table but the agent cannot use it | registered in `permissions.py`, absent from the agent's tool list | None | S | Remove from the SECURITY.md table or implement |
| N12 | The offline router answers unrecognised questions with the business overview | "Am I approved?", "What is my IBAN ...?" and "show my transactions" all return the overview; "Can you guarantee I get the loan?" is answered as if it were an application | Low-medium | S | Add an honest "I didn't understand" reply |

Known and accepted (already in SECURITY R3): the injection filter misses paraphrases
("Disregard everything you were told before ..."), role-play requests and languages
outside its six (Japanese and Korean were tried). None of 8 benign finance questions
tried was wrongly blocked.

---

## 6. Real-data backtest (UCI Online Retail II) - done

Dataset: Chen, D. (2012), *Online Retail II*, UCI Machine Learning Repository,
https://doi.org/10.24432/C5CG6D, licence CC BY 4.0 (read from the dataset's own page).
A UK online gift-ware retailer, 1 December 2009 to 9 December 2011.

- `scripts/uci_download.py` downloads it into `data/external/` (git-ignored, not committed) and cleans it: 1,067,371 invoice lines, of which 19,494 cancellations, 3,457 non-positive quantities, 2,750 non-positive prices and 4,793 non-product codes are dropped; 1,036,877 kept; 739 calendar days, 135 with no sales (kept as zeros).
- `scripts/uci_backtest.py` runs the product's own sales projection, unchanged and untuned, from 80 forecast dates (one every 7 days) and scores the next 14, 30 and 60 days. Nothing is fitted to this data.
- No new dependency: the spreadsheet is read with the Python standard library.

Error on total sales over the horizon, % of actual sales, mean over forecast dates (median in brackets):

| Horizon | Our forecast | Repeat last week | Weekday average, 8 weeks | Same weekday last year* |
|---|---:|---:|---:|---:|
| 14 days | 32.6% (13.3%) | 35.3% (19.4%) | 36.7% (14.0%) | 15.0% (10.8%) |
| 30 days | 18.7% (10.5%) | 27.8% (16.2%) | 24.2% (11.0%) | 10.6% (10.9%) |
| 60 days | 19.1% (11.8%) | 29.6% (20.7%) | 25.9% (14.5%) | 7.4% (7.4%) |

\* Needs a year of history: the last 45 of the 80 dates. On those 45, ours is 24.6% (15.0%) at 60 days.

What it means:
- **It beats the naive forecasts that only use recent weeks** at 30 and 60 days, and is about level at 14 days.
- **It loses clearly to "same weekday last year".** Our monthly seasonal table was written for the sandbox and under-states this retailer's Christmas peak.
- The averages are pulled up by the Christmas shutdown, which the forecaster knows nothing about: the worst 14-day forecast (made 22 December 2010) predicted GBP 639,108 against GBP 58,495.
- **Scope:** sales only. The data has no payouts, so this says nothing about the payout model.

A safe sentence for questions: "On two years of a real retailer's sales our forecast beats repeating last week, but not last year's own data, so using the seller's own last year is our next step."

---

## 7. Deck change list

File: `SME-Finance-Copilot-Pitch.pptx` (13 main + 3 appendix slides). **Not edited.**
The deck is built by `scripts/build_deck.js` from `docs/evidence/facts.json`, so
re-running that script (it needs Node; I did not run it) should produce most of these
changes. Check each slide against this list either way.

| Slide | Old text | New text | Why |
|---|---|---|---|
| 7 Demo | "-EUR 5,084 on 4 October" | "-EUR 5,055 on 4 October" | seasonality fix |
| 7 | "Needs EUR 6,584" | "Needs EUR 6,555" | seasonality fix |
| 7 | "she recovers to EUR 2,815 by day 60" | "she recovers to EUR 2,671 by day 60" | seasonality fix |
| 7 | "Cause: Textil Nord GmbH, EUR 6,800" | keep, and add: "Underneath: payout timing. EUR 8,459 of her own earnings is still in the payout queue that day, more than the whole gap." | A5: the product now says this itself (hand edit; not in the build script) |
| 8 Differentiator | "Granary Supplier Payment Terms EUR 196" | "EUR 195" | bridge amount is EUR 30 smaller |
| 8 | "Ember Seasonal Bridge EUR 218" | "EUR 217" | same |
| 8 | "SwiftCash Merchant Advance EUR 1,844" | "EUR 1,835" ("~98% effective APR" stays) | same |
| 9 What-if | "STARTING FROM A LOW POINT OF -EUR 5,084" | "-EUR 5,055" | seasonality fix |
| 9 | "Pay the supplier 3 weeks later ... low point -EUR 3,925" | "-EUR 4,081" | monthly bills now on their real dates |
| 9 | "payouts arrive 3 days late ... low point -EUR 5,412" | "-EUR 5,378" | seasonality fix |
| 9 | "Take Ember Seasonal Bridge ... low point EUR 959" | "EUR 780" | monthly bills now on their real dates |
| 9 | "Take SwiftCash Merchant Advance ... low point -EUR 796" | "-EUR 927" | same |
| 11 Evidence | "3.1% consistency check" | "1.5%" | seasonality and monthly-bill fixes |
| 11 | "19.4% when payouts arrive 0-3 days late: the real weak spot, published" | "9.5% when payouts arrive 0-3 days late (1,200 simulated backtests): the real weak spot, published" | stress tool fixed and re-measured; N1 fix |
| 11 | "232 tests" | "367 tests" | new regression tests |
| 11 (optional, hand edit) | - | a third number: "19% error on a real retailer's 60-day sales: beats repeating last week (30%), loses to last year's data (7%)" | first evidence on data we did not generate |
| 14 Appendix A1 | "An output guardrail enforces that, not just a prompt." | until N6 is fixed: "A system rule and an output check for the most direct wordings back that up." | the guardrail lets "your loan is approved" through |
| 16 Appendix A3 | "with 232 tests" | "with 367 tests" | new tests |
| 6 (optional) | "names the payment causing the squeeze" | "names the payment causing the squeeze and the payout hold behind it" | A5 |

Unchanged and still true: slide 1 (EUR 5,007, EUR 3,180), slide 2 (EUR 10,991,
EUR 620, EUR 6,800, 25 September, 14 days / 10-day hold, 13.7 days), slide 5
(13.7 days), slide 8 (47 days, 6 days, 7 / 6 / 1 days to arrange), slide 14 (Lina:
7.9%, EUR 3,967, 8 months, EUR 253), slide 16 (18 scenarios, 12 known risks, 6
languages). If the team approves B9, "13.7 days" on slides 2 and 5 becomes about 16.3.

### Old figures still in the repository, each checked

Command: a `grep` over the repository (without `.git`, `.venv`, `data/external` and
this report) for 3.1%, 19.4, 47.9, 5,084, 6,584, EUR 218, EUR 196, 1,844, 2,815, 3,925,
5,412, EUR 959, -EUR 796, "232 tests" and 4,921.

| Where | Figure | Still true? |
|---|---|---|
| TECHNICAL.md 3.6, SECURITY.md R1 | "the submitted version reported 19.4% / 47.9%" | Yes: a statement about the past |
| TECHNICAL.md 3.7, `uci_backtest.json` | 19.4%, 47.9% | Yes: a coincidence, these are UCI figures (a median and a 14-day mean) |
| `docs/evidence/llm_live_run.md`, `llm_live_audit.jsonl` | -5,084, 6,584, 218, 1,844, 196, 3,925 | A recording of 18 October; now labelled as made before the fixes |
| The `.pptx` | all of the above | No: see the table above |

---

## 8. Improvement suggestions (not built)

Ranked by effect on judges per hour of work.

| # | What | Why a judge would care | Effort | Risk |
|---|---|---|---|---|
| 1 | **Make the live demo safe:** fix N4 (time-out) and N6 (guardrail wordings), then rehearse once with Wi-Fi off | A hung screen or a "your loan is approved" slip costs more marks than any feature gains. Security is 30% of the marking | S (1-2 hours) | Very low |
| 2 | **Show the late-payout risk on the main chart:** a second, lighter line for "if payouts slip 3 days", using the existing what-if | Turns the measured weak spot (9.5%, section 3) into something visible, and answers "how sure are you?" without claiming a precision we don't have | S-M | Low: display only, no number changes |
| 3 | **"Shorter hold" what-if - a thin slice of the Payout Engine:** let the seller ask "what if my hold were 3 days, not 10?" (for merchant-fulfilled sellers: ship faster, paid sooner) | It puts a euro figure on the product's own thesis and offers a free fix before any loan | M | Medium: a new what-if path; keep it out of the baseline so no existing number moves |
| 4 | **Use the seller's own last year for seasonality when a year of history exists** | Section 6 shows why: 7.4% against our 19.1% on real data. "We tested on real data, found we lost to last year's numbers, and fixed it" is a strong answer | M | Low for the demo: the sandbox has 6 months of history, so its numbers do not change |
| 5 | **Path-level backtest:** measure the error in the date of the lowest point (days) and in the bridge amount, on windows that contain a declared bill | Closes the two gaps in section 4 (Tier 3): today no backtest covers the situation the product exists for | M-L | Medium: needs earlier bills in the generated history, which regenerates the dataset and moves every number. Do it only if there is time to update the deck again |

On the three ideas already on the table:
- **Path-level backtest metrics:** worth doing (number 5), but only useful together with backtest windows that contain a bill; on today's windows the lowest point is trivial.
- **Calibrated forecast intervals checked by coverage:** not recommended before the final. Calibrated on the sandbox they are circular, as you noted; calibrated on UCI they would cover sales only, while the measured risk is payout timing. Suggestion 2 gives most of the benefit honestly.
- **Full Payout Engine** (per-channel profiles, settlement calendar, delivery-based hold): the best long-term direction and the best "what's next" slide, but large and risky in the days left. Build only the thin slice in suggestion 3. A weekend-free settlement calendar is small but moves every number.

---

## 9. Open questions for the team

1. **Approval:** which of N2, N3, N4, N6, N9, N10, N11, N12 (section 5) should be fixed? Recommended at least N4 and N6. Also B9 (moves "13.7 days" on two slides) and B8.
2. **Branch name:** the default branch is `master`. The pull request targets it. Say so if you wanted a `main` branch.
3. **Live-LLM transcript:** re-run `python scripts/live_llm_check.py` with your key after the last fix, so `docs/evidence/llm_live_run.md` shows current figures. I did not run it and did not create or read any `.env`.
4. **Deck:** edit by hand from section 7, or re-run `scripts/build_deck.js`?
5. **Rules questions for `info@ican-x.com`:**
   - The UCI dataset (CC BY 4.0) is used for testing only and is not in the repository. Is testing on a public dataset compatible with "completed independently"?
   - The deck font, Archivo Black, is under the SIL Open Font License: a clear open licence, but not one of MIT / Apache-2.0 / BSD / CC BY 4.0. It was already in the submitted version. Is it acceptable, or should the deck use a system font?
6. **Dependency licences** were read from the installed packages' own metadata (FastAPI MIT, Uvicorn BSD-3-Clause, Pydantic MIT, Anthropic SDK Apache-2.0, pytest MIT) and are now in the README.

---

## 10. Tests and commits

`pytest -q` on `finals`: **367 passed** (submitted version: 232).

| Commit | What |
|---|---|
| `f0196c0` | Fix seasonality double-count in growth estimate (audit B1 / risk R12) |
| `d0cae72` | Fix stress-test harness: late payouts land late or stay pending, never vanish |
| `a2af87d` | First version of this report; R12 commit reference |
| `cde4ba7` | Fix A2: a bill due today or overdue and unpaid is charged on day one |
| `32afce8` | Fix B6: a payout delayed past the last forecast day is pending, not deleted |
| `3ad4669` | Fix B10: never print "for roughly None days" |
| `5c1962f` | Fix A3: several payments added together are never called "one payment" |
| `04b9b35` | A4: explain bridge span (47 days) versus days below the buffer (43) |
| `1d0bcd4` | Fix N1: expect a payout that is due but has not reached the bank |
| `c080fc5` | Fix B2: project monthly bills on their day of the month |
| `a1287f2` | Fix A5: name payout timing as a cause, with the amount held |
| `6932410` | Fix B4 (sales per calendar day) and disclose the limits of the accuracy check |
| `c19ef5b` | Step 4: keep forecast findings visible to the model; correct two doc statements |
| `5dc7018` | Step 5: real-data backtest of the sales forecast on UCI Online Retail II |
| `2d9e298` | Label the recorded live-LLM transcript as pre-fix |
| `4da9784` | Add requirements-dev.txt (pytest) and list dependency licences |
| (latest) | This report |

One deviation from "one commit per logical change": `6932410` holds B4 and the accuracy
disclosures together, because they shared one regeneration of the evidence.

---

## Reminder: the team's own checklist (not done by the assistant)

- Top up Claude API credit (about USD 5) before the final.
- Confirm a spend cap is set on the key. The key stays in the local `.env` only.
- Email `info@ican-x.com` with the rules questions in section 9.
