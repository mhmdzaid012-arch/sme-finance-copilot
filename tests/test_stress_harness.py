"""
Tests for the stress-test harness itself (scripts/stress_test.py).

The harness submitted in October deleted any payout scheduled within 3 days of
the end of the history instead of delaying it, and shared one random generator
across all four sellers. A measurement tool with a bug measures the bug, so the
harness now has tests of its own:

  * a late payout lands later with the same amount, or is still pending
  * it is never dropped: every euro is in the bank or in the platform balance
  * each seller's draws are independent of every other seller's
  * with no stress applied, the harness reproduces the committed dataset
"""

from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app import config

sys.path.insert(0, str(config.ROOT / "scripts"))
import generate_data as g  # noqa: E402
import stress_test as st  # noqa: E402

SELLERS = st.SELLERS
JITTER = 3


def _ledger(data_dir) -> list[dict]:
    with (data_dir / "transactions.csv").open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _bank_payouts(rows: list[dict], seller_id: str) -> dict[str, tuple[str, float]]:
    """memo ('release of sales through X') -> (landing date, amount)."""
    return {r["memo"]: (r["date"], float(r["amount"])) for r in rows
            if r["seller_id"] == seller_id and r["ledger"] == "bank" and r["type"] == "payout"}


def _platform_balance(rows: list[dict], seller_id: str) -> float:
    return sum(float(r["amount"]) for r in rows
               if r["seller_id"] == seller_id and r["ledger"] == "platform")


@pytest.fixture(scope="module")
def on_time() -> list[dict]:
    with st.stressed_world() as (data_dir, _):
        return _ledger(data_dir)


def test_unstressed_harness_reproduces_the_committed_dataset():
    with st.stressed_world() as (data_dir, payout_log):
        generated = (data_dir / "transactions.csv").read_bytes()
        assert payout_log == {}
    assert generated == (config.ROOT / "data" / "transactions.csv").read_bytes()


def test_harness_restores_the_real_dataset_afterwards():
    before = config.DATA_DIR
    with st.stressed_world(jitter=JITTER, seed=1):
        assert config.DATA_DIR != before
    assert config.DATA_DIR == before
    assert g.payout_landing_date(None, date(2026, 9, 10)) == date(2026, 9, 10)


@pytest.mark.parametrize("seed", range(1, 9))
def test_late_payouts_are_delayed_or_pending_never_dropped(seed, on_time):
    """
    For every seller and every scheduled payout: it either lands 0-3 days late
    with exactly the amount it would have paid on time, or it has not landed
    by the end of the history and its money is still in the platform balance.
    """
    with st.stressed_world(jitter=JITTER, seed=seed) as (data_dir, payout_log):
        late = _ledger(data_dir)

    for sid in SELLERS:
        base, got = _bank_payouts(on_time, sid), _bank_payouts(late, sid)
        pending_total = 0.0
        for memo, (due, amount) in base.items():
            due_date = date.fromisoformat(due)
            if memo in got:
                landed, late_amount = got[memo]
                delay = (date.fromisoformat(landed) - due_date).days
                assert 0 <= delay <= JITTER, (sid, memo, delay)
                assert late_amount == amount, (sid, memo)
            else:
                # Only a payout pushed past the end of the history may be absent.
                landing = dict(payout_log[sid])[due_date]
                assert landing > config.AS_OF, (sid, memo, landing)
                pending_total += amount
        assert set(got) <= set(base), f"{sid}: the harness invented a payout"
        # Conservation: what did not reach the bank is still on the platform.
        assert _platform_balance(late, sid) == pytest.approx(
            _platform_balance(on_time, sid) + pending_total, abs=0.01), sid


def test_a_payout_pushed_past_the_end_of_the_history_is_carried(on_time):
    """
    TechFix has a payout scheduled on the last day of the history. The old
    harness always deleted it. Here it is forced 3 days late: it must be
    absent from the bank and present, in full, in the platform balance.
    """
    sid = "techfix-parts"
    base = _bank_payouts(on_time, sid)
    last_memo, (last_due, last_amount) = max(base.items(), key=lambda kv: kv[1][0])
    assert date.fromisoformat(last_due) == config.AS_OF

    original = g.payout_landing_date
    try:
        g.payout_landing_date = lambda cfg, scheduled: scheduled + timedelta(days=3)
        with st.stressed_world() as (data_dir, _):
            late = _ledger(data_dir)
    finally:
        g.payout_landing_date = original

    got = _bank_payouts(late, sid)
    assert last_memo not in got
    assert len(got) == len(base) - 1
    assert _platform_balance(late, sid) == pytest.approx(
        _platform_balance(on_time, sid) + last_amount, abs=0.01)


def test_each_seller_has_an_independent_generator():
    """One seller's draws must not depend on which other sellers are drawn."""
    days = [date(2026, 3, 9) + timedelta(days=14 * i) for i in range(12)]
    a, b = SimpleNamespace(seller_id="seller-a"), SimpleNamespace(seller_id="seller-b")

    alone, _ = st.late_landing(JITTER, seed=5)
    a_alone = [alone(a, d) for d in days]

    mixed, _ = st.late_landing(JITTER, seed=5)
    a_mixed = []
    for d in days:
        mixed(b, d)
        a_mixed.append(mixed(a, d))
        mixed(b, d)
    assert a_alone == a_mixed

    other_seed, _ = st.late_landing(JITTER, seed=6)
    assert [other_seed(a, d) for d in days] != a_alone


def test_late_landing_is_reproducible_and_bounded():
    days = [date(2026, 3, 2) + timedelta(days=7 * i) for i in range(60)]
    cfg = SimpleNamespace(seller_id="seller-a")
    first, log = st.late_landing(JITTER, seed=11)
    second, _ = st.late_landing(JITTER, seed=11)
    run1, run2 = [first(cfg, d) for d in days], [second(cfg, d) for d in days]
    assert run1 == run2
    delays = {(landed - due).days for due, landed in log["seller-a"]}
    assert delays == {0, 1, 2, 3}


def test_in_transit_flag():
    pairs = [(date(2026, 9, 7), date(2026, 9, 9)), (date(2026, 8, 24), date(2026, 8, 24))]
    assert st.straddles(pairs, date(2026, 9, 7))
    assert st.straddles(pairs, date(2026, 9, 8))
    assert not st.straddles(pairs, date(2026, 9, 9))
    assert not st.straddles(pairs, date(2026, 8, 24))
