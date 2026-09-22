# SME Finance Copilot

An AI finance copilot for **e-commerce micro-sellers**, the small online shops that
make money every month and still can't make a supplier payment, because their cash is
sitting in a marketplace payout queue.

Built for the WeBank Fintechathon International Track, Topic E (SME Finance Copilot).
Theme: *AI as a Financial Participant*.

> **Everything here runs on simulated sandbox data.** No real business, bank account,
> marketplace or lender is represented. The financing catalog is illustrative and its
> providers are fictional. This tool does not underwrite, does not approve credit, and
> is not financial advice.

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. That's the whole setup, and **no API key is required**
(see [Two modes](#two-modes)).

You can regenerate everything at any time:

```bash
python scripts/generate_data.py        # deterministic synthetic ledger
python scripts/generate_evidence.py    # evidence pack, stress test and facts.json
pytest -q                              # 195 tests
```

---

## What it does

**1. Cash-flow management with alerts.** Projects the bank balance day by day, finds
the lowest point, and tells the seller how much is needed, for how long, and how many
days they have to arrange it. Alerts name the payments that cause the squeeze and rank
the fixes cheapest-first, with the free options before any borrowing.

**2. Financing-option matching.** Checks the seller against 18 illustrative products,
one criterion at a time. Every product it recommends is **simulated end to end** first,
including the date the money actually arrives and the real repayment schedule, so a
product that looks cheap on paper but whose repayments open a new hole next month is
never recommended.

**3. Business financial analysis.** Contribution margin, break-even revenue, the
monthly cash left over after all regular payments, peer comparison, and a number
sellers are almost never shown: how much of their own money is trapped in the payout
queue, measured in days of sales.

**4. What-if simulator.** Change an assumption and see the projection next to the
baseline: pay a bill later or split it, cut ads, sales rising or falling, payouts
arriving late, a new monthly cost, or taking a specific financing product. It works
from the web panel or in plain English ("what if I pay the supplier 3 weeks late?").
It projects only and never changes anything.

### The problem, concretely

Amara's Prints turns over about EUR 11,000 a month and has about EUR 620 a month left
after all regular payments, including a loan repayment. On 10 September she has
EUR 3,180 in the bank and EUR 5,007 she has already earned sitting in the payout queue.
A EUR 6,800 stock payment is due on 25 September.

The copilot's answer: her balance goes negative on **25 September** and bottoms out at
**-EUR 5,084** on 4 October. She needs about **EUR 6,584 for 47 days**, and she has
**6 days** to arrange it. The cheapest matching product, Granary Supplier Payment Terms
at EUR 196, takes 7 days to arrange, so it can't be her first line of defence. The copilot
recommends Ember Seasonal Bridge at EUR 218, which arrives in time. It also simulated
Ember with its real repayments first, and it keeps her out of the red. Before any of
that, it suggests asking for an early payout and talking to the supplier, which cost
nothing.

The distinction between *how long money is needed for* and *how long there is to
arrange it* is exactly what a generic assistant gets wrong.

---

## Two modes

| | Planning | Narrative | Needs a key |
|---|---|---|---|
| **LLM mode** | Claude chooses the tools | Claude writes the reply | yes |
| **Offline mode** | Deterministic intent router | Templates | no |

Set `ANTHROPIC_API_KEY` for LLM mode. Without it, the copilot runs offline.

**Offline mode is not a stub.** It exists so the repository behaves the same for
anyone who clones it, with no credential, no network call and no cost. If a model is
configured but unavailable in the middle of a session, the turn falls back to offline
mode instead of failing. LLM mode is implemented, but it has not been exercised
against the live API in this sandbox. See risk R11 in [docs/SECURITY.md](docs/SECURITY.md).

The key property in both modes: **the tools do the financial reasoning, not the model.**
Every figure comes from deterministic Python, and the model only plans and phrases.

---

## Architecture

```
                 ┌──────────────────────────────────────────┐
  browser ─────► │  FastAPI  (app/main.py)                  │
                 └──────────────┬───────────────────────────┘
                                │
                 ┌──────────────▼───────────────────────────┐
                 │  Agent  (app/agent.py)                   │
                 │  input guardrails → plan → output guards │
                 └──────────────┬───────────────────────────┘
                                │  permission check + audit on every call
     ┌────────────┬─────────────┼─────────────┬──────────────┐
     ▼            ▼             ▼             ▼              ▼
 forecast.py  financing.py  analysis.py   alerts.py     whatif.py
 two-ledger   per-criterion plain-English composes the  scenarios +
 projection   matching      analysis      others        verification
     └────────────┴─────────────┴─────────────┴──────────────┘
                                │
                 ┌──────────────▼───────────────────────────┐
                 │  store.py - sandbox ledger + metrics     │
                 └──────────────────────────────────────────┘

  security/  permissions.py (T0/T1/T2 + human confirmation)
             guardrails.py  (injection defence in 6 languages)
             audit.py       (hash-chained append-only log)
  facts.py   single source for every figure quoted in the docs and deck
```

Full detail: **[docs/TECHNICAL.md](docs/TECHNICAL.md)**.

---

## Security

The design claim is narrow and testable: **the agent cannot take a consequential
action on its own, even if the model is fully compromised.** This is enforced by
what the agent can call, not by instructions. Action-tier tools don't execute
anything. They return a single-use, expiring confirmation token tied to the exact
details the user was shown. `confirm_action` is *not a registered agent tool*, so a
prompt-injected model has nothing to call.

Sessions start **advice-only**, and the interface only lets the assistant *prepare*
actions after the user switches that on. Each session can only read its own audit
records. The sandbox ledger contains a real planted prompt-injection attack in a
customer order note, and the guardrails detect injection attempts in English, Chinese,
Arabic, German, French and Spanish, including disguised spellings.

Full self-assessment and known-risk list: **[docs/SECURITY.md](docs/SECURITY.md)**.

---

## How accurate is the forecast?

We report two numbers, because one of them alone would mislead.

**Consistency check: 3.1% mean error, 6.5% worst case** (as a share of monthly
revenue, across 12 backtests). This compares the forecast with the sandbox ledger.
The ledger was generated by the same process the forecaster assumes, so this only
shows that the model behaves as designed. It is not proof of real-world accuracy.

**Stress test: accuracy when the assumptions are wrong.** `scripts/stress_test.py`
regenerates the data with the assumptions deliberately broken and runs the backtests
again. The biggest sensitivity is payout timing. When marketplace payouts arrive 0-3
days late at random, the mean error rises to **19.4%**, because a single late payout
moves a whole payment across the date being measured. That's why the what-if
simulator has a "payouts arrive late" setting: a seller can test this weakness on
their own projection. Full table: [docs/TECHNICAL.md](docs/TECHNICAL.md#36-measured-accuracy).

---

## Project layout

```
app/
  main.py            FastAPI routes
  agent.py           orchestration, guardrail pipeline, offline router
  store.py           sandbox data access + derived metrics
  facts.py           every figure quoted outside the code
  config.py          parameters (all forecasting constants live here)
  tools/
    forecast.py      two-ledger projection, scenarios, backtest
    financing.py     per-criterion eligibility + true cost of capital
    analysis.py      plain-English financial analysis
    alerts.py        ranked alerts; financing verified by simulation
    whatif.py        what-if simulator + recommendation verification
  security/
    permissions.py   tiers, staging, human confirmation
    guardrails.py    multilingual injection / scope / output checks
    audit.py         hash-chained audit log
data/                generated ledger, financing catalog, peer benchmarks
docs/
  TECHNICAL.md       architecture, algorithms, security design
  SECURITY.md        security self-assessment + known-risk list
  evidence/          sandbox logs, transcripts, backtests, stress test, facts.json
scripts/
  generate_data.py       deterministic dataset generator
  generate_evidence.py   evidence pack + facts.json
  stress_test.py         accuracy when assumptions are broken
  build_deck.js          pitch deck, built from facts.json
static/index.html    single-file UI, no external dependencies
tests/               195 tests
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status and active mode |
| GET | `/api/sellers` | Sandbox seller directory |
| GET | `/api/seller/{id}` | Profile and derived metrics |
| GET | `/api/seller/{id}/forecast?horizon_days=` | Cash-flow projection |
| GET | `/api/seller/{id}/alerts` | Alerts and verified mitigations |
| GET | `/api/seller/{id}/analysis` | Financial analysis |
| POST | `/api/seller/{id}/financing` | Financing matches |
| GET | `/api/seller/{id}/whatif/options` | Bills and products available to simulate |
| POST | `/api/seller/{id}/whatif` | Run a what-if scenario |
| GET | `/api/seller/{id}/backtest?horizon_days=` | Forecast consistency check |
| POST | `/api/session` | Start a session (advice-only by default) |
| POST | `/api/chat` | One conversational turn |
| POST | `/api/confirm` | **Human-only** action approval |
| GET | `/api/security/tiers` | Permission model |
| GET | `/api/audit?session_id=` | Your own session's audit records |
| GET | `/api/audit/verify` | Verify the hash chain |

## Deployment notes

It runs as a single process, with no database and no external services.
`uvicorn app.main:app --host 0.0.0.0 --port 8000` behind any reverse proxy is enough
for a demo deployment.

Two things are demo-grade, and we call them out rather than hide them. Sessions live
in process memory, so a restart clears them. There's also no user authentication: the
random session id works as the credential, which is acceptable only because every
seller is fictional. Both are listed as known risks, with the change a production
deployment would need.

## Licence and data

This is original work for the Fintechathon International Track. It uses no
third-party data, code or open-source components beyond the declared dependencies
(FastAPI, Uvicorn, Pydantic, and optionally the Anthropic SDK). All seller data,
transactions, balances, financing products, provider names and peer benchmarks are
synthetic and generated by the scripts in this repository.
