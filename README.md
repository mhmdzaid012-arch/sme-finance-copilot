# SME Finance Copilot

An AI finance copilot for **e-commerce micro-sellers** — the small online shops that
are profitable on paper yet regularly cannot make a supplier payment, because their
money is sitting in a marketplace payout queue.

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

Open <http://127.0.0.1:8000>.

That is the whole setup. **No API key is required** — see [Two modes](#two-modes).

Regenerate the dataset or the evidence pack at any time:

```bash
python scripts/generate_data.py        # deterministic synthetic ledger
python scripts/generate_evidence.py    # sandbox operation logs + backtests
pytest -q                              # 132 tests
```

---

## What it does

Three capabilities, matching the topic brief.

**1. Cash-flow management with alerts.** Projects the bank balance forward day by day,
finds the trough, and says how much is needed, for how long, and how many days there
are to arrange it. Alerts name the specific payments that cause the squeeze and rank
mitigations cheapest-first — free levers before any borrowing.

**2. Financing-option matching.** Matches the seller against 18 illustrative products
across eight real product categories. Every product is evaluated per-criterion, with
the requirement and the seller's actual value shown side by side. Rejections state
which test failed and what would have to change.

**3. Business financial analysis.** Contribution margin, break-even revenue, expense
mix, peer comparison, and the number almost no seller is ever shown: how much of their
own money is trapped in the payout queue, expressed as days of sales.

### The problem, concretely

Amara's Prints turns over about €11,000/month and makes roughly €800/month profit. On
10 September she has €3,180 in the bank and €5,007 earned but not yet paid out. A
€6,800 stock payment is due on 25 September.

The copilot's answer: she goes negative on **25 September**, bottoms out at
**−€7,536** on 18 October, needs about **€9,036 for 54 days**, and has **7 days** to
arrange it. It then notes that inventory finance would be the cheapest fit at €356 —
*but takes 10 days to arrange, so it cannot help this time* — and recommends the
€299 option that can, after first suggesting she ask for an early payout and talk to
her supplier, both of which are free.

That distinction between *how long money is needed for* and *how long there is to
arrange it* is the kind of thing a generic assistant gets wrong.

---

## Two modes

| | Planning | Narrative | Needs a key |
|---|---|---|---|
| **LLM mode** | Claude chooses the tools | Claude writes the reply | yes |
| **Offline mode** | Deterministic intent router | Templates | no |

Set `ANTHROPIC_API_KEY` for LLM mode; without it the copilot runs offline.

**Offline mode is not a stub.** It exists so that this repository behaves identically
for anyone who clones it, with no credential, no network call and no cost — including
the judges. If the model is configured but unavailable mid-session, the turn degrades
to offline rather than failing.

The important property either way: **the tools do the financial reasoning, not the
model.** Every figure comes from deterministic Python. The model plans and phrases. A
language model should not be the component deciding whether a seller can make payroll.

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
        ┌───────────────┬───────┴────────┬────────────────┐
        ▼               ▼                ▼                ▼
  forecast.py     financing.py      analysis.py       alerts.py
  deterministic   explainable       plain-English     composes the
  cash projection rule engine       translation       other three
        └───────────────┴────────────────┴────────────────┘
                                │
                 ┌──────────────▼───────────────────────────┐
                 │  store.py — sandbox ledger + metrics     │
                 └──────────────────────────────────────────┘

  security/  permissions.py (T0/T1/T2 + human confirmation)
             guardrails.py  (direct & indirect prompt injection)
             audit.py       (hash-chained append-only log)
```

Full detail in **[docs/TECHNICAL.md](docs/TECHNICAL.md)**.

---

## Security

The design claim is narrow and testable: **the agent cannot take a consequential
action on its own, even if the model is fully compromised.**

That is enforced by capability separation rather than instructions. Action-tier tools
do not execute — they return a single-use, expiring confirmation token bound to a hash
of the exact payload the user was shown. `confirm_action` is *not a registered agent
tool*, so a prompt-injected model has nothing to call.

The sandbox ledger contains a **real planted prompt-injection attack** in a customer
order note, so the defence is demonstrated on the actual data rather than asserted.
Ask any question about Amara's Prints and the copilot reports it.

Full self-assessment, including the known-risk list and what this design does *not*
solve: **[docs/SECURITY.md](docs/SECURITY.md)**.

---

## Is the forecast any good?

It is measured, not asserted. `scripts/generate_evidence.py` backtests every seller at
30/45/60-day horizons by forecasting from a past date and comparing against the actual
ledger:

**Mean absolute error 2.5% of monthly revenue; worst case 6.5%.**

Those figures exclude one-off payments that were neither recurring nor declared as
scheduled obligations when the forecast was made — genuinely unforecastable, and
reported separately rather than hidden. That residual is the method's single biggest
limitation and the reason the product asks sellers to declare known upcoming bills:
Amara's raw 30-day error is €4,921, of which €4,500 is one undeclared supplier deposit.

Full table: [docs/evidence/scenarios.md](docs/evidence/scenarios.md).

---

## Project layout

```
app/
  main.py            FastAPI routes
  agent.py           orchestration, guardrail pipeline, offline router
  store.py           sandbox data access + derived metrics
  config.py          parameters (all forecasting constants live here)
  tools/
    forecast.py      deterministic cash-flow projection + backtest
    financing.py     per-criterion eligibility + true cost of capital
    analysis.py      plain-English financial analysis
    alerts.py        ranked alerts and mitigations
  security/
    permissions.py   tiers, staging, human confirmation
    guardrails.py    injection / scope / output checks
    audit.py         hash-chained audit log
data/                generated ledger, financing catalog, peer benchmarks
docs/
  TECHNICAL.md       architecture, algorithms, security design
  SECURITY.md        security self-assessment + known-risk list
  evidence/          sandbox operation logs, transcripts, backtests
scripts/
  generate_data.py       deterministic dataset generator
  generate_evidence.py   evidence pack generator
static/index.html    single-file UI, no external dependencies
tests/               132 tests
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status and active mode |
| GET | `/api/sellers` | Sandbox seller directory |
| GET | `/api/seller/{id}` | Profile and derived metrics |
| GET | `/api/seller/{id}/forecast?horizon_days=` | Cash-flow projection |
| GET | `/api/seller/{id}/alerts` | Alerts and mitigations |
| GET | `/api/seller/{id}/analysis` | Financial analysis |
| POST | `/api/seller/{id}/financing` | Financing matches |
| GET | `/api/seller/{id}/backtest?horizon_days=` | Measured forecast accuracy |
| POST | `/api/session` | Start a session (tier defaults to advice-only) |
| POST | `/api/chat` | One conversational turn |
| POST | `/api/confirm` | **Human-only** action approval |
| GET | `/api/security/tiers` | Permission model |
| GET | `/api/audit` | Audit records + chain status |
| GET | `/api/audit/verify` | Verify the hash chain |

## Deployment notes

Single process, no database, no external services. `uvicorn app.main:app --host 0.0.0.0
--port 8000` behind any reverse proxy is sufficient for a demo deployment.

Two things that are demo-grade and deliberately called out rather than hidden: sessions
are held in process memory (a restart clears them), and there is no authentication —
seller selection is unauthenticated because every seller is fictional. Both are listed
in the known-risk list with the change a production deployment would require.

## Licence and data

Original work for the Fintechathon International Track. No third-party data, code or
open-source components beyond the declared dependencies (FastAPI, Uvicorn, Pydantic,
and optionally the Anthropic SDK). All seller data, transactions, balances, financing
products, provider names and peer benchmarks are synthetic and generated by the scripts
in this repository.
