# Finals report - SME Finance Copilot (Team Finova)

Working branch: `finals`. The submitted version is commit `537c0d8` and is untouched.
Note: the repository's default branch is called `master`, not `main`.

**Status on 11 November 2026: Steps 0, 1, 2 and 3 are done. Waiting for the team's
approval of the fix list in section 4 before changing anything else.**
Steps 4-7 have not been started.

How to continue if this session is interrupted: read this file, run `git log --oneline`,
then run `pytest -q` (expect 264 passed). The next action is whatever the team approves
from the fix list in section 4.

All commands below were run from the repository root with the project's virtual
environment (`.venv/bin/python`). "Monthly revenue" always means the seller's average
monthly revenue over the previous 90 days.

---

## 1. Summary

1. Fixed the seasonality double-count (R12) and the broken stress-test harness. Both have regression tests.
2. Amara's numbers barely moved: lowest balance -EUR 5,084 -> -EUR 5,055, amount needed EUR 6,584 -> EUR 6,555, still 47 days, same dates, same recommended product.
3. The accuracy figures did move: consistency check 3.1% -> 2.7%; late-payout stress test 19.4% (worst 47.9%) -> 15.2% (worst 41.0%), now over 1,200 backtests instead of 12.
4. Still open: 12 audit findings are still present (section 4), none fixed yet because they need approval. The deck and the recorded live-LLM transcript still show the old numbers.
5. Tests: 232 -> 264, all passing.

---

## 2. Before / after table

"Before" is the submitted version (`537c0d8`), regenerated into a temporary folder.
"After" is the `finals` branch at commit `d0cae72`.

Commands:
- Before: `git archive 537c0d8 | tar -x -C <tmp>` then, inside `<tmp>`, `python scripts/generate_evidence.py`. The output matched the committed `docs/evidence/` exactly, except `audit_log.jsonl`, which contains timestamps and random turn ids and so differs on every run.
- After: `python scripts/generate_evidence.py` on `finals`, then read `docs/evidence/facts.json`, `backtest_results.json` and `stress_test.json`.

| Number | Before | After | Where it appears |
|---|---:|---:|---|
| Tests passing (`pytest -q`) | 232 | 264 | README, TECHNICAL, SECURITY, facts.json, deck |
| Consistency check, mean error (% of monthly revenue) | 3.1% | 2.7% | README, TECHNICAL 3.6, SECURITY R1, scenarios.md, facts.json, deck |
| Consistency check, worst case | 6.5% | 6.5% | same |
| Stress test, late payouts, mean | 19.4% | 15.2% | README, TECHNICAL 3.6, SECURITY R1, stress_test.json, facts.json, deck |
| Stress test, late payouts, worst | 47.9% | 41.0% | TECHNICAL 3.6, stress_test.json |
| Stress test, late payouts, median | not reported | 5.6% | README, TECHNICAL 3.6, SECURITY R1 |
| Stress test, late payouts, number of backtests | 12 | 1,200 | TECHNICAL 3.6, stress_test.json |
| Stress test, noisier sales, mean / worst | 4.4% / 9.5% | 4.5% / 9.4% | TECHNICAL 3.6 |
| Stress test, unknown seasonality, mean / worst | 8.3% / 16.8% | 9.0% / 16.7% | TECHNICAL 3.6 |
| Stress test, all three, mean / worst | 26.6% / 46.4% | 22.2% / 49.9% | TECHNICAL 3.6 |
| Amara: growth factor per 28 days | 1.0376 | 1.0150 | forecast "assumptions", UI |
| Amara: first day below the EUR 1,500 buffer | 16 Sep | 16 Sep | alerts |
| Amara: first day below zero | 25 Sep | 25 Sep | README, deck |
| Amara: lowest balance (the "trough") | -EUR 5,084 on 4 Oct | -EUR 5,055 on 4 Oct | README, scenarios.md, deck, llm_live_run.md |
| Amara: amount needed (bridge amount) | EUR 6,584 | EUR 6,555 | README, scenarios.md, deck, llm_live_run.md |
| Amara: bridge days (first dip to final recovery) | 47 | 47 | README, scenarios.md, deck |
| Amara: days actually below the buffer | 43 | 43 | forecast findings, what-if text |
| Amara: days to arrange it | 6 | 6 | README, deck |
| Amara: balance on day 60 | EUR 2,815 | EUR 2,671 | facts.json, deck chart |
| Recommended product and cost | Ember Seasonal Bridge, EUR 218 | Ember Seasonal Bridge, EUR 217 | README, TECHNICAL 4.4, deck |
| Cheapest product overall (too slow) | Granary Supplier Payment Terms, EUR 196 | same, EUR 195 | README |
| Merchant cash advance cost | EUR 1,844 | EUR 1,835 | TECHNICAL 4.4, deck |
| Amara 30-day backtest, raw error | EUR 4,921 | EUR 4,827 | TECHNICAL 3.6, SECURITY R1 |
| What-if "pay supplier 3 weeks later", new lowest balance | -EUR 3,925 | -EUR 3,901 | scenarios.md, deck |
| What-if "payouts 3 days late", new lowest balance | -EUR 5,412 | -EUR 5,378 | scenarios.md, deck |
| What-if "take Ember", new lowest balance | EUR 959 | EUR 960 | scenarios.md, deck |

### Why each number moved, in plain words

- **Growth factor (1.0376 -> 1.0150).** The old code compared the last 28 days of sales with the 28 days before, without removing the calendar effect. September is a stronger month than August in the seasonal table (1.04 vs 0.90), so part of the "growth" was just the calendar. With the calendar effect removed first, the measured growth is lower. Amara's true built-in growth is 3.5% a month; 1.5% is within the noise of a 28-day measurement (see section 5, note on noise).
- **Amara's lowest balance and bridge amount (about EUR 30 better).** Slightly lower projected sales mean slightly lower stock, shipping and ad costs before the low point, while the payouts that arrive before 4 October come mostly from sales already made. The net effect before the low point is +EUR 30. The dates did not move.
- **Balance on day 60 (EUR 144 lower).** Lower projected sales over two months means less money coming in later.
- **Financing costs (EUR 1 to EUR 9 lower).** They are calculated on the bridge amount, which is EUR 30 smaller. The recommendation itself is unchanged: Ember Seasonal Bridge is still the cheapest product that arrives in time and keeps her out of the red.
- **Consistency check (3.1% -> 2.7%).** The growth estimate no longer carries the calendar effect, so the forecasts are a little closer to the ledger. Amara's three backtests improved the most (3.8%, 2.8%, 1.7% -> 3.0%, 2.0%, 1.1%).
- **Stress test, late payouts (19.4% -> 15.2%, worst 47.9% -> 41.0%).** This is the harness fix, not the forecaster. See section 3.

---

## 3. Stress test: what was wrong, what changed, and the sentence to use

### Was it ever fixed? No.

`git log --follow scripts/stress_test.py` shows one commit only (`6bd8a50`, 22 September): the file was never changed after it was created. Running the old logic and counting payouts (script: old harness logic, 0 vs 3 days of jitter) showed:

| Seller | Payouts on time | Payouts in the old "late" run | Money left in the platform balance |
|---|---:|---:|---:|
| TechFix | 14 | 13 | EUR 9,669 -> EUR 26,786 |

TechFix has a payout scheduled on 10 September, the last day of the history. The old harness deleted it (about EUR 17,000) in every run, whatever the random draw. All three TechFix backtests then showed errors of 47.6%, 43.0% and 44.1% (old harness logic, run on the code after the seasonality fix). That is 3 of the 12 backtests, and it is where the old 47.9% worst case and most of the old 19.4% mean came from. The old harness also used one random-number generator for all four sellers, and it moved the sales window of each payout together with its date, so "late" payouts also released extra sales.

### What the harness does now (commit `d0cae72`)

- A late payout releases exactly the sales it was scheduled to release and lands 0-3 days later.
- If that pushes it past the end of the history, it is still pending and its money stays in the platform balance. It is never dropped. Tests check this euro for euro.
- Each seller has its own seeded random generator.
- Because one set of random delays is a coin flip, the late-payout rows are repeated over 100 sets (1,200 backtests each).
- `tests/test_stress_harness.py` (14 tests). The committed dataset is unchanged, byte for byte (checked with `cmp`).

### New result

Command: `python scripts/stress_test.py` (about 13 seconds).

| Scenario | Mean | Worst | Backtests |
|---|---:|---:|---:|
| Same process the forecaster assumes | 2.7% | 6.5% | 12 |
| Daily sales twice as noisy | 4.5% | 9.4% | 12 |
| A seasonal pattern the forecaster doesn't know | 9.0% | 16.7% | 12 |
| Payouts 0-3 days late at random | 15.2% | 41.0% | 1,200 |
| All three at once | 22.2% | 49.9% | 1,200 |

Distribution of the late-payout row: median 5.6%, 90th percentile 38.1%.

The error is not spread evenly. It depends on whether a payout happens to be "in transit" (due, but not yet landed) on one of the two dates that matter:

| Late-payout backtests | Count | Mean error | Direction |
|---|---:|---:|---|
| No payout in transit on either date | 690 | 2.4% (worst 6.5%) | same as the baseline |
| Payout in transit on the day the forecast is made | 273 | 27.1% (worst 37.0%) | forecast too low |
| Payout in transit on the day the forecast is measured | 237 | 38.6% (worst 41.0%) | forecast too high |

(The first table comes from `stress_test.json`; the three-way split was measured with a one-off script that re-runs the same 100 sets.)

Two honest caveats:
- The share of affected backtests (510 of 1,200) is specific to this sandbox: every backtest is measured on the same date, 10 September, and TechFix has a payout scheduled exactly then. The split (about 2% vs about 30%) is the finding that carries over, not the 15.2% average.
- The middle row is a weakness in the product, not only bad luck. The forecaster works out which payouts have been paid from the schedule, not from the payouts actually visible in the bank ledger. If a payout is late on the day of the forecast, it assumes the money has already arrived and never counts it. This is fixable (item N1 in the fix list).

### Wording decision

The harness is fixed and re-measured, so the figure can be quoted, with its method.

**Sentence for the deck (short):**
> Late payouts are our biggest forecast risk: when payouts slip 0-3 days, the average error rises from 2.7% to 15.2% of monthly revenue (1,200 simulated backtests).

**Sentence for the docs (already in README, TECHNICAL.md, SECURITY.md in this form):**
> When marketplace payouts arrive 0-3 days late at random, the mean error rises to 15.2% (median 5.6%, worst case 41.0%, over 1,200 backtests with 100 sets of random delays). The error is concentrated: when a payout is in transit on the day the forecast is made or the day it is measured, the error averages 32.4%, and otherwise 2.4%.

**If a judge asks why it changed from 19.4%:** "Our own review found that the test tool deleted some late payouts instead of delaying them. We fixed the tool, added tests for it, and re-ran it 100 times instead of once."

Do not say 19.4% or 47.9% anywhere any more.

### The same family of bug in the product (audit B6): still present

In the what-if "payouts arrive late" scenario, a payout pushed past the last day of the forecast is left out, and the reply does not say so. Measured for Amara over 53 days with a 3-day delay: 4 payouts become 3, EUR 5,182 is missing, and the reply says "Balance at the end of the 53 days: EUR 3,441 becomes -EUR 1,741". The lowest-balance and days-below-buffer figures are right; the ending balance is misleading. The 60-day chat demo (scenario S15) is not affected. The web what-if panel uses 90 days, where it does happen for Lina (delay of 3 days or more) and for Kofi and TechFix (7 days). Fix is item B6 in the list below and needs approval.

---

## 4. Audit status table

Checked with a probe script against commit `d0cae72`. File and line numbers refer to that commit.

| Item | Status | Evidence | Demo severity | Fixed in |
|---|---|---|---|---|
| B1 seasonality double-count | **Fixed** | Flat test seller, November start: growth 1.1964 -> 1.0000; sales error day 60 +46.9% -> 0.0%, day 180 +216.7% -> 0.0%. January: floor 0.80 -> 1.0000; -38.0% / -76.2% -> 0.0%. `tests/test_seasonality_growth.py` (18 tests, all failed before the fix) | - | `f0196c0` |
| Stress harness (Step 2) | **Fixed** | Section 3 | - | `d0cae72` |
| A1 early payout picked a payout after the shortfall | **Fixed** (already, before this session) | `alerts.py:189` only picks a payout dated after the first dip. Existing tests `test_early_payout_lever_names_a_payout_that_lands_after_the_dip` (all 4 sellers) pass. Amara: dip 16 Sep, payout offered 21 Sep | - | before `537c0d8` |
| A2 bill due today or overdue is dropped | **Still present** | `forecast.py:279,282` use `as_of < due`. Adding a EUR 2,000 bill due on 10 Sep or 7 Sep changes nothing (lowest balance stays -5,055); due 11 Sep it becomes -7,055 | Medium | - |
| A3 "one payment" is several payments summed | **Still present, hidden** | `forecast.py:399-408` adds up by name. In all 20 seller x horizon combinations tested, the top driver is a single payment, so the demo never shows it. A seller whose biggest driver is rent would see three rents called "one payment" | Low | - |
| A4 47 bridge days vs 43 days below buffer | **Not a bug - labelling** | 47 = first dip (16 Sep) to final recovery (1 Nov). 43 = days actually below (the balance is above the buffer on 21-24 Sep). A bridge cannot be handed back for 4 days, so 47 is the right financing duration, and `match_financing` receives 47. TechFix shows the same gap more strongly: 49 vs 31. Nothing explains the two numbers to the user | Low | - |
| A5 payout timing can never be named as a driver | **Still present** | `primary_drivers` only lists bills. Amara's drivers: Textil Nord, rent, wages, loan. A separate "money stuck in the payout queue" alert exists, but only at "info" level and only when there is already a gap | **High** (it is the product's thesis) | - |
| B2 monthly bills drift | **Still present** | Rent is paid on the 1st; projected on 2 Oct, 2 Nov, 3 Dec, 3 Jan, 3 Feb, 6 Mar. Wages (30th) projected 30 Sep, 31 Oct, 1 Dec. One day off inside the 60-day demo | Medium | - |
| B3 quarterly and annual bills can't be detected | **Still present** | Three quarterly payments (Jan, Apr, Jul) are not detected: the rule needs 3 payments inside 180 days. Amara's July VAT is treated as a one-off surprise in her 60-day backtest | Low in demo | - |
| B4 baseline averages rows, not days | **Still present** | Same sales split into 4 order rows per day: Monday baseline EUR 448 -> EUR 112, 60-day projected sales EUR 26,549 -> EUR 6,637. The sandbox has one row per day, so demo numbers are right. Must be fixed before any real-data test (Step 5) | None in demo, blocks Step 5 | - |
| B5 stock on hand starts at zero | **Limitation, not triggered** | There is no input for stock already owned on the forecast date. In the sandbox every seller pays product cost per order, and future stock arrives with its bill (`inventory_value`), so nothing is charged twice in the demo | None in demo | - |
| B6 delayed payout past the horizon disappears | **Still present** | Section 3 | Medium | - |
| B7 refund and chargeback rates | **Still present, small** | Amara: the sandbox marketplace deducts 4.10% for refunds from each payout; the forecaster measures 3.27% over 56 days (3.41% over the whole history). Chargebacks: 0.68% measured over 56 days vs 0.42% over the whole history, and charged on the day of sale, not 8-20 days later | Low | - |
| B8 what-if bill changes match by name only | **Still present, hidden** | Two bills from the same supplier: delaying "Textil Nord GmbH" by 10 days moved both. No sandbox seller has two future bills with one name | Low | - |
| B9 "days of sales trapped" mixes net and gross | **Still present** | Amara: EUR 5,007 (after fees) divided by gross daily sales = 13.7 days; like for like it is 16.3. The payout-queue alert only fires when there is already a gap: Lina has the most trapped cash (17.4 days) and gets no such alert | Low-medium | - |
| B10 "for roughly None days" | **Not reachable in normal use** | 24 seller x horizon combinations, every alert text scanned: 0 hits. It only appears with a negative safety buffer | Low | - |

### Tier 3 - how strong is the accuracy evidence?

Measured on the 12 standard backtests (probe script, `d0cae72`).

| Weakness | Measured | Do the docs say so today? |
|---|---|---|
| Only the balance on the last day is compared, not the lowest point, its date or the bridge amount | By reading `backtest()` (`forecast.py:493`) | **No** |
| No backtest covers a scheduled bill | All windows end on 10 Sep; the earliest declared bill is due 25 Sep | **No** |
| The "undeclared one-offs" adjustment removes most of the error | Amara: 95.9% of the raw error removed (EUR 16,013 -> EUR 663 across her 3 backtests). All 12: 63.6%. Without the adjustment the mean error is 14.4% of monthly revenue (worst 59.2%), against the 2.7% we quote | **Partly.** The docs mention the EUR 4,500 deposit. They don't give the unadjusted 14.4% |
| The adjustment excuses bills the seller knew about | The two excused payments are Amara's own stock deposit (EUR 4,500, 20 Aug) and her quarterly VAT (EUR 1,850, 15 Jul). The docs call the deposit "never declared"; a real seller would have declared both | **No** (described as unforecastable) |
| Error is divided by monthly revenue, not by balance | Divided by the closing balance the mean is 6.1%, not 2.7% | **Yes** (TECHNICAL 3.6 explains the choice, without the 6.1%) |
| The seasonal table in `config.py` is a copy of the data generator's | `config.py:47` and `generate_data.py:324` are identical; the comment says "Mirrors scripts/generate_data.py". This makes the consistency check circular for seasonality. Not changed, as instructed | **Yes** (described as a consistency check) |

### Fix list - waiting for approval

Effort: S = under an hour, M = half a day, L = a day or more. "Moves numbers" means the deck and docs must be updated again.

| # | Item | Effort | Risk to the demo | Recommendation |
|---|---|---|---|---|
| 1 | **A5** Name the payout hold as a cause: show how much of the gap is the seller's own money waiting in the queue, in the headline alert | M | Medium. Changes the hero alert text, so the deck wording changes. No forecast number moves | **Fix.** A judge who has just heard the pitch will look for this sentence |
| 2 | **N1** (new, from Step 2) Work out which payouts have been paid from the bank ledger, not from the schedule | M | Low. Hero numbers should not move (all sandbox payouts are on time); to be confirmed by the tests | **Fix.** Removes the 27.1% error group in the stress test |
| 3 | **B6** Show a delayed payout that falls past the end of the forecast as "still pending" and say so in the what-if reply | S | Low. The 60-day hero what-if is unchanged | **Fix.** Reachable in the web panel for Lina, Kofi and TechFix |
| 4 | **A2** Keep bills due today or overdue and unpaid, charge them on day 1, mark them "overdue" | S-M | Low. No sandbox bill is due on or before 10 Sep, so no number moves | **Fix** |
| 5 | **B2** Project monthly bills on their day of the month | S-M | Medium. **Moves numbers**: rent lands on the 1st, not the 2nd, so Amara's figures may shift slightly | **Fix**, in the same round as other number-moving changes |
| 6 | **Tier 3 disclosure** Add the unadjusted error (14.4%), the balance-based figure (6.1%) and the two missing caveats to TECHNICAL.md, and stop calling Amara's deposit "never declared" | S | None (docs only) | **Fix.** Cheapest way to be safe under questioning |
| 7 | **A3** Say "payments to X" when several were added up, and only say "one payment" when it is one | S | None in the demo | Fix |
| 8 | **B10** Never print "None days" | S | None | Fix |
| 9 | **A4** One line in the alert and UI explaining "47 days from the first dip to the final recovery; below the buffer on 43 of them" | S | Low. Text only | Fix |
| 10 | **B4** Add up sales per calendar day (including days with no sales) before averaging | S | None (sandbox numbers do not change) | Fix if Step 5 (real-data test) goes ahead; needed for it |
| 11 | **B9** Compare like with like in "days of sales trapped" and let the alert fire without a gap | S | Medium. **Moves a deck number** (13.7 -> about 16.3 days) | Team decision |
| 12 | **B8** Match what-if bill changes on name and due date | S | Low | Optional |
| 13 | **B3** Detect quarterly bills | M | Low | Leave; disclose as a limitation |
| 14 | **B7** Lag-aware refund and chargeback rates | M | Low | Leave; disclose |
| 15 | **B5** Opening stock input | M | Low | Leave; disclose |

Suggested order if all of 1-10 are approved: 4, 3, 8, 7, 9 (small, no numbers move), then 2, then 5 (numbers move once), then 1, then 6, then 10.

---

## 5. New findings from Step 4

Not started. Items already noticed in passing (not yet verified in full):

- `docs/TECHNICAL.md` section 10, point 7 says "LLM mode hasn't been exercised against the live API". README and SECURITY R11 say it was run live on 18 October. Contradiction.
- `docs/evidence/llm_live_run.md` is a recording of that live run and still shows the old figures (-EUR 5,084, EUR 6,584, EUR 218). It can only be refreshed by running `scripts/live_llm_check.py` with the team's API key. I did not run it and did not read any `.env`.
- The baseline sales level is the 56-day average, with growth applied from today onward. For a growing seller this starts the projection about one growth step too low. Not yet measured.
- The growth estimate is noisy: a 28-day against 28-day comparison on sales with 16% daily noise has a spread of roughly 4 percentage points, which is larger than Amara's true 3.5% monthly growth. Not yet measured properly.
- N1 (see fix list): payouts already paid are inferred from the schedule, not read from the ledger.

## 6. UCI Online Retail II backtest

Not started. Depends on B4 (item 10) being fixed first.

## 7. Deck change list

Not started in full. Already certain, because `scripts/build_deck.js` reads `facts.json`: every slide that shows -EUR 5,084, EUR 6,584, EUR 218, EUR 1,844, 3.1%, 19.4% or "232 tests" needs the new value from section 2. The list by slide will be written once the approved fixes are in, so the team edits the deck once.

## 8. Improvement suggestions

Not started.

## 9. Open questions for the team

1. Which items in the fix list (section 4) are approved, and in which order?
2. The default branch is `master`, not `main`. The pull request will target `master` unless you say otherwise.
3. The live-LLM transcript (`docs/evidence/llm_live_run.md`) needs a re-run with your API key after the last number-moving fix. Do you want to do it before the final, or label the file as "recorded on 18 October, before the finals fixes"?
4. Licensing question for `info@ican-x.com`: none so far. (The UCI dataset in Step 5 is CC BY 4.0, which is on the allowed list.)

## 10. Tests and commits

`pytest -q` on `finals`: **264 passed** (submitted version: 232).

| Commit | What |
|---|---|
| `f0196c0` | Fix seasonality double-count in growth estimate (audit B1 / risk R12) |
| `d0cae72` | Fix stress-test harness: late payouts land late or stay pending, never vanish |
| (this commit) | Finals report, R12 commit reference |

---

## Reminder: the team's own checklist (not done by the assistant)

- Top up Claude API credit (about USD 5) before the final.
- Confirm a spend cap is set on the key. The key stays in the local `.env` only.
- Email `info@ican-x.com` with any rules or licensing question listed in section 9.
