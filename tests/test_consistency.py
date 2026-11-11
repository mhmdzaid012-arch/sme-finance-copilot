"""
No contradictions: between the data and itself, the system and its evidence,
and the system and every document that quotes it.

These tests exist because contradictions were found by hand and fixed:
  * the deck said Amara makes EUR 800 a month; the tool said EUR 998
  * two sellers declared loan repayments that never appeared in their ledger
  * a supplier note claimed a deposit that was never paid
  * the deck said Lina could get "a grant" for working capital; the engine
    excludes grants for working capital
  * the accuracy claim described a consistency check as real-world accuracy
Each one is now a failing test if it comes back.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from app import config
from app.facts import build_facts, eur, pretty_date
from app.store import detect_recurring, get_seller

SELLERS = ["amara-prints", "kofi-coffee", "linas-ceramics", "techfix-parts"]
DOCS = {
    "README.md": config.ROOT / "README.md",
    "TECHNICAL.md": config.DOCS_DIR / "TECHNICAL.md",
    "SECURITY.md": config.DOCS_DIR / "SECURITY.md",
}
DECK_SCRIPT = config.ROOT / "scripts" / "build_deck.js"
FACTS_PATH = config.EVIDENCE_DIR / "facts.json"

# Figures that were once published and are now wrong. None may reappear.
STALE = ["EUR 800", "€", "7,536", "9,036", "9,816", "132 tests", "2.5%",
         "54 days", "EUR 4,963", "10,995", "EUR 299", "EUR 356"]


@pytest.fixture(scope="module")
def stored_facts() -> dict:
    assert FACTS_PATH.exists(), "run scripts/generate_evidence.py"
    return json.loads(FACTS_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The data does not contradict itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seller_id", SELLERS)
def test_declared_loan_repayments_exist_in_the_ledger(seller_id):
    ctx = get_seller(seller_id)
    declared = float(ctx.profile["monthly_debt_service"])
    in_ledger = sum(r["amount"] for r in detect_recurring(ctx) if r["category"] == "debt_service")
    assert in_ledger == pytest.approx(declared), (
        f"{seller_id} declares EUR {declared}/month of loan repayments "
        f"but the ledger shows EUR {in_ledger}")


@pytest.mark.parametrize("seller_id", SELLERS)
def test_notes_do_not_claim_payments_that_never_happened(seller_id):
    ctx = get_seller(seller_id)
    for o in ctx.profile["scheduled_obligations"]:
        if "deposit" in o.get("note", "").lower() and "already paid" in o["note"].lower():
            paid = [t for t in ctx.transactions
                    if t.counterparty == o["counterparty"] and t.amount < 0]
            assert paid, f"{o['counterparty']} note claims a deposit the ledger never paid"


@pytest.mark.parametrize("seller_id", SELLERS)
def test_stock_purchases_are_marked_as_stock(seller_id):
    """Otherwise the forecaster would charge for the same goods twice."""
    for o in get_seller(seller_id).profile["scheduled_obligations"]:
        if o["category"] == "supplier":
            assert o.get("inventory_value", 0) > 0, o["counterparty"]


# ---------------------------------------------------------------------------
# The evidence matches the running system
# ---------------------------------------------------------------------------

def test_facts_file_matches_the_live_system(stored_facts):
    live = json.loads(json.dumps(build_facts(), default=str))
    for key in ("hero", "lina", "surplus_by_seller", "whatif_demo", "planted_attack", "security"):
        assert stored_facts[key] == live[key], (
            f"facts.json '{key}' is stale - run scripts/generate_evidence.py")
    for key in ("consistency_mean_pct", "consistency_worst_pct", "hero_backtest_30d"):
        assert stored_facts["accuracy"][key] == live["accuracy"][key], key


def test_facts_file_reports_the_real_number_of_tests(stored_facts):
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                         cwd=config.ROOT, capture_output=True, text=True).stdout
    collected = int(re.search(r"(\d+) tests? collected", out).group(1))
    assert stored_facts["counts"]["tests"] == collected


# ---------------------------------------------------------------------------
# Every document quotes the system correctly
# ---------------------------------------------------------------------------

def _required_phrases(f: dict) -> dict[str, list[str]]:
    h, a = f["hero"], f["accuracy"]
    late = next(r for r in a["stress"]["results"] if r["key"] == "late_payouts")
    bt = a["hero_backtest_30d"]
    tests = f"{f['counts']['tests']} tests"
    hero = [
        eur(h["monthly_cash_surplus"]), eur(h["bank_balance"]), eur(h["platform_balance"]),
        eur(h["bill_amount"]), pretty_date(h["first_negative_date"]),
        eur(h["trough_balance"]), pretty_date(h["trough_date"]),
        eur(h["need_amount"]), f"{h['need_days']} days", f"{h['lead_days']} days",
        eur(h["payout_queue_at_trough"]),
        h["recommended"]["name"], eur(h["recommended"]["cost"]),
        h["cheapest_overall"]["name"], eur(h["cheapest_overall"]["cost"]),
    ]
    accuracy = [f"{a['consistency_mean_pct']}%", f"{a['consistency_worst_pct']}%",
                f"{late['mean_pct']}%"]
    return {
        "README.md": hero + accuracy + [tests],
        "TECHNICAL.md": accuracy + [
            # The accuracy figure is never quoted without its unadjusted and
            # balance-based versions.
            f"{a['unadjusted_mean_pct']}%", f"{a['unadjusted_worst_pct']}%",
            f"{a['balance_based_mean_pct']}%", f"{a['one_off_share_of_raw_error_pct']}%",
            eur(bt["raw_error"]), eur(bt["undeclared_one_offs"]), tests,
            eur(h["mca"]["cost"]), eur(h["recommended"]["cost"]),
            f"{f['counts']['transactions']:,} transactions",
            f"{f['counts']['evidence_scenarios']} scenarios",
            f"{f['counts']['audit_records']} audit records",
        ] + [f"{r['mean_pct']}%" for r in a["stress"]["results"]],
        "SECURITY.md": [f"{late['mean_pct']}%", tests, f"{a['consistency_mean_pct']}%",
                        eur(bt["raw_error"]), eur(bt["undeclared_one_offs"]),
                        f"{f['counts']['audit_records']} records"],
    }


@pytest.mark.parametrize("doc", list(DOCS))
def test_documents_quote_the_live_figures(doc, stored_facts):
    text = DOCS[doc].read_text(encoding="utf-8")
    missing = [p for p in _required_phrases(stored_facts)[doc] if p not in text]
    assert not missing, f"{doc} is missing or misquotes: {missing}"


@pytest.mark.parametrize("doc", list(DOCS) + ["build_deck.js"])
def test_no_stale_figures_anywhere(doc):
    path = DECK_SCRIPT if doc == "build_deck.js" else DOCS[doc]
    text = path.read_text(encoding="utf-8")
    found = [s for s in STALE if _quoted_as_a_whole_figure(s, text)]
    assert not found, f"{doc} still contains stale figures: {found}"


def _quoted_as_a_whole_figure(stale: str, text: str) -> bool:
    """True if `stale` appears as a figure of its own, not inside a longer
    number: "2.5%" must be caught, "42.5%" (a current figure) must not."""
    before = r"(?<![\d.,])" if stale[0].isdigit() else ""
    after = r"(?!\d)" if stale[-1].isdigit() else ""
    return re.search(before + re.escape(stale) + after, text) is not None


def test_stale_figure_check_matches_whole_figures_only():
    assert _quoted_as_a_whole_figure("2.5%", "the error was 2.5% then")
    assert _quoted_as_a_whole_figure("EUR 800", "she makes EUR 800 a month")
    assert _quoted_as_a_whole_figure("€", "costs €5")
    assert not _quoted_as_a_whole_figure("2.5%", "worst case 42.5%")
    assert not _quoted_as_a_whole_figure("EUR 800", "about EUR 8000")


def test_deck_takes_every_figure_from_the_facts_file():
    """No euro amount may be typed into the deck by hand."""
    src = DECK_SCRIPT.read_text(encoding="utf-8")
    assert "facts.json" in src
    literals = re.findall(r'["\'`][^"\'`\n]*EUR \d', src)
    assert not literals, f"hard-coded amounts in the deck: {literals[:5]}"


def test_real_data_backtest_figures_in_the_docs_match_the_evidence_file():
    """The UCI figures are published in two documents; both must match the file."""
    uci = json.loads((config.EVIDENCE_DIR / "uci_backtest.json").read_text(encoding="utf-8"))
    h60 = uci["all_origins"]["60"]
    for doc in ("README.md", "TECHNICAL.md"):
        text = DOCS[doc].read_text(encoding="utf-8")
        for method in ("model", "last_week", "last_year"):
            assert f"{h60[method]['total_error_mean_pct']}%" in text, (doc, method)
        assert "CC BY 4.0" in text and "10.24432/C5CG6D" in text, doc
    assert uci["dataset"]["licence"] == "CC BY 4.0"


def test_recorded_live_run_is_current_or_labelled_as_old(stored_facts):
    """The live-LLM transcript cannot be regenerated without an API key. It must
    either quote today's figures or say plainly that it predates them."""
    text = (config.EVIDENCE_DIR / "llm_live_run.md").read_text(encoding="utf-8")
    current = eur(stored_facts["hero"]["need_amount"]) in text
    assert current or "Recorded before the finals fixes" in text


def test_third_party_data_is_never_committed():
    ignored = (config.ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/external/" in ignored and ".env" in ignored
    tracked = subprocess.run(["git", "ls-files", "data/external", ".env"], cwd=config.ROOT,
                             capture_output=True, text=True).stdout.strip()
    assert tracked == "", f"must not be committed: {tracked}"


def test_accuracy_is_never_described_as_real_world_without_the_stress_result():
    for doc, path in DOCS.items():
        text = path.read_text(encoding="utf-8")
        if "consistency" in text.lower() or "backtest" in text.lower():
            assert "stress" in text.lower(), f"{doc} quotes accuracy without the stress test"


# ---------------------------------------------------------------------------
# Market claims are held to the same standard as product claims
# ---------------------------------------------------------------------------

MARKET_PATH = config.ROOT / "data" / "market.json"


@pytest.fixture(scope="module")
def market() -> dict:
    return json.loads(MARKET_PATH.read_text(encoding="utf-8"))


def test_every_measured_market_figure_names_a_real_source(market):
    for key, entry in market["measured"].items():
        src = market["sources"].get(entry.get("source"))
        assert src, f"{key} cites no source"
        assert src["url"].startswith("https://"), f"{key} source has no link"
        assert src["publisher"] and src["reference_year"], key


def test_every_derived_market_figure_shows_its_method_and_its_caveat(market):
    """A number we computed ourselves may never look like a published one."""
    for key, entry in market["derived"].items():
        assert entry.get("method"), f"{key} does not say how it was computed"
        assert entry.get("caveat"), f"{key} does not say what it assumes"
        assert "source" not in entry, f"{key} is derived but claims a source"


def test_the_revenue_arithmetic_on_the_market_slide_is_correct(market):
    d = market["derived"]
    expected = (d["deployment_active_sellers"]["value"]
                * d["price_per_seller_month_eur"]["value"] * 12)
    assert d["deployment_annual_revenue_eur"]["value"] == pytest.approx(expected)


def test_no_derived_enterprise_count_exceeds_the_measured_population(market):
    m, d = market["measured"], market["derived"]
    for key, entry in d.items():
        if entry["unit"] in ("enterprises", "businesses"):
            assert entry["value"] <= m["eu_micro_enterprises"]["value"], key
    assert d["adjacent_smes"]["value"] <= m["eu_smes"]["value"]


def test_the_extrapolated_beachhead_is_not_reintroduced(market):
    """Eurostat does not survey firms under 10 employees, so a micro-enterprise
    'selling online' count cannot be derived from its rates. Keep it out."""
    assert "beachhead_sellers" not in market["derived"]
    deck = DECK_SCRIPT.read_text(encoding="utf-8")
    assert "beachhead_sellers" not in deck and "som_capture_pct" not in deck


def test_the_deck_takes_every_market_figure_from_the_market_file():
    """No market number may be typed into the deck by hand either."""
    src = DECK_SCRIPT.read_text(encoding="utf-8")
    assert "market.json" in src
    typed = re.findall(r'["\'`][^"\'`\n]*\b\d[\d.,]*\s?(?:million|billion|trillion|m EU|%\s)', src)
    assert not typed, f"hand-typed market figures in the deck: {typed[:5]}"


def test_lina_is_never_promised_a_grant_for_working_capital(stored_facts):
    """Grants are excluded for working capital; no document may say otherwise."""
    grants = set(stored_facts["lina"]["excluded_wrong_purpose"])
    assert not grants & set(stored_facts["lina"]["eligible_names"])
    for doc in list(DOCS.values()) + [DECK_SCRIPT]:
        assert "microloans and a grant" not in doc.read_text(encoding="utf-8")
