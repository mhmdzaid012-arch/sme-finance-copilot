"""Regression tests for the October hardening pass.

Each test pins one defect found in review so it cannot come back:
  * the early-payout lever named a payout that could not help
  * forecast/backtest horizons accepted negative or absurd values
  * the web app sent no security headers
  * /api/chat had no rate limit (a cost-abuse risk in LLM mode)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent import _horizon
from app.tools.alerts import generate_alerts
from app.tools.forecast import forecast_cashflow

client = TestClient(main.app)


# --- early payout lever ------------------------------------------------------

def _early_payout(ctx):
    fc = forecast_cashflow(ctx, 60)
    alerts = generate_alerts(ctx, fc)
    lever = next((m for m in alerts["mitigations"]
                  if m["action"].startswith("Request an early")), None)
    return fc, lever


def test_early_payout_lever_names_a_payout_that_lands_after_the_dip(any_seller):
    fc, lever = _early_payout(any_seller)
    if lever is None:
        return
    first_dip = fc["findings"]["first_below_buffer_date"]
    # A payout landing before the dip is already in the forecast; asking for it
    # earlier cannot help, so it must never be offered.
    assert lever["payout_date"] > first_dip


def test_early_payout_lever_states_what_it_does_not_fix(amara):
    fc, lever = _early_payout(amara)
    assert lever is not None
    # Amara is still short after the payout lands (the stock bill), so the
    # lever must say it does not close the gap rather than imply it does.
    assert lever["covers_whole_gap"] is False
    assert "does not close the later gap" in lever["detail"]


# --- input bounds -------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/seller/amara-prints/forecast?horizon_days=-5",
    "/api/seller/amara-prints/forecast?horizon_days=100000",
    "/api/seller/amara-prints/alerts?horizon_days=0",
    "/api/seller/amara-prints/backtest?horizon_days=99999",
])
def test_out_of_range_horizons_are_rejected(path):
    assert client.get(path).status_code == 422


def test_in_range_horizon_still_works():
    r = client.get("/api/seller/amara-prints/forecast?horizon_days=90")
    assert r.status_code == 200 and r.json()["horizon_days"] == 90


@pytest.mark.parametrize("raw,expected", [
    ({"horizon_days": -40}, 7), ({"horizon_days": 10_000}, 180),
    ({"horizon_days": "abc"}, 60), ({}, 60), ({"horizon_days": 30}, 30),
])
def test_model_supplied_horizon_is_clamped(raw, expected):
    assert _horizon(raw) == expected


# --- security headers ---------------------------------------------------------

def test_security_headers_on_ui_and_api():
    for path in ("/", "/api/health"):
        h = client.get(path).headers
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-frame-options"] == "DENY"
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"


# --- chat rate limit ----------------------------------------------------------

def test_chat_is_rate_limited_per_session(monkeypatch):
    monkeypatch.setattr(main, "CHAT_MAX_TURNS", 3)
    sid = client.post("/api/session", json={"seller_id": "amara-prints"}).json()["session_id"]
    codes = [client.post("/api/chat", json={"session_id": sid, "message": "hello"}).status_code
             for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    # A different session has its own budget.
    other = client.post("/api/session", json={"seller_id": "amara-prints"}).json()["session_id"]
    assert client.post("/api/chat", json={"session_id": other, "message": "hello"}).status_code == 200


# --- wording ------------------------------------------------------------------

def test_supplier_names_keep_their_capitals_in_the_summary():
    sid = client.post("/api/session", json={"seller_id": "amara-prints"}).json()["session_id"]
    reply = client.post("/api/chat", json={"session_id": sid,
                                            "message": "Will I run out of cash?"}).json()["reply"]
    assert "Textil Nord" in reply and "textil nord" not in reply


# --- local .env loading ---------------------------------------------------------

def test_dotenv_is_read_but_never_overrides_the_environment(tmp_path, monkeypatch):
    from app import config
    env = tmp_path / ".env"
    env.write_text('# comment\nSMEFC_TEST_A="from file"\nSMEFC_TEST_B=from file\n', encoding="utf-8")
    monkeypatch.delenv("SMEFC_TEST_A", raising=False)
    monkeypatch.setenv("SMEFC_TEST_B", "from shell")
    config._load_dotenv(env)
    import os
    assert os.environ["SMEFC_TEST_A"] == "from file"
    assert os.environ["SMEFC_TEST_B"] == "from shell"
    monkeypatch.delenv("SMEFC_TEST_A")


def test_tests_run_offline_even_with_a_local_key():
    from app import config
    assert config.agent_mode() == "offline"


# --- output guardrail: honest disclaimers must pass ---------------------------

from app.security.guardrails import check_output  # noqa: E402


@pytest.mark.parametrize("text", [
    "Approval is not guaranteed.", "Approval isn't guaranteed.",
    "Approval cannot be guaranteed.", "The loan must be personally guaranteed.",
])
def test_honest_disclaimers_are_not_blocked(text):
    # The live LLM run had a correct reply withheld for exactly this wording.
    assert check_output(text) == []


@pytest.mark.parametrize("text", [
    "You are approved for EUR 5,000.", "This loan is guaranteed.",
    "No problem, you're approved.", "No worries; this is guaranteed.",
    "You will definitely get the money.",
])
def test_real_approval_claims_are_still_blocked(text):
    assert check_output(text)
