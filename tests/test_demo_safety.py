"""
Demo-safety tests added for the finals (findings N4 and N6).

N6: the output guardrail caught three exact wordings, so "Your loan is
    approved" went through. It now covers the common wordings of each
    forbidden claim, and still lets honest, hedged sentences pass.
N4: LLM mode had no time-out (the SDK default is 600 seconds with retries),
    so a bad network could freeze a live turn. Calls and whole turns are now
    time-limited and fall back to offline mode.

No test here contacts the network: the model client is replaced by a fake.
"""

from __future__ import annotations

import sys
import types

import pytest

from app import agent, config
from app.security import guardrails as gr
from app.security.permissions import T1_RECOMMEND, Session

# --- N6: forbidden claims ------------------------------------------------------

@pytest.mark.parametrize("claim", [
    "Your loan is approved.",
    "You are pre-approved for EUR 5,000",
    "You're approved!",
    "Good news: the facility has been approved.",
    "You've been approved for a bridge of EUR 6,555.",
    "You are now officially approved",
    "Approval has been granted.",
    "You are cleared for a loan of EUR 5,000",
    "We guarantee this facility will be granted",
    "I can guarantee you get it",
    "You will definitely get the money",
    "You're certain to qualify",
    "You'll surely qualify for it",
    "I have submitted your application.",
    "I've just filed it for you",
    "The application has been sent to the lender",
    "Consider it done - funds are on the way",
    "The money has been transferred to your account",
])
def test_forbidden_claims_are_blocked_in_their_common_wordings(claim):
    assert gr.check_output(claim), claim


@pytest.mark.parametrize("honest", [
    "Approval is not guaranteed.",
    "I cannot guarantee anything.",
    "A lender still has to assess the application.",
    "Assumes the application is approved on the stated terms. Matching published "
    "criteria is not a credit decision.",
    "If it is approved, the money arrives on 16 September.",
    "Once approved, you would repay in 4 instalments.",
    "Whether it gets approved is the lender's decision.",
    "It needs to be approved by the lender first.",
    "You are not approved for anything; a lender decides.",
    "Approval is likely but the lender decides.",
    "I have prepared an application for Ember Seasonal Bridge - but I have not "
    "submitted it, and I cannot.",
    "The application would be sent only after you confirm.",
    "Nothing has been sent.",
    "This loan is personally guaranteed by the owner.",
    "The payout was sent by the marketplace on 7 September.",
    "You match the published criteria for 6 products.",
])
def test_honest_and_hedged_sentences_still_pass(honest):
    assert gr.check_output(honest) == [], honest


@pytest.mark.parametrize("name", ["scenarios.md", "llm_live_run.md"])
def test_no_recorded_reply_trips_the_wider_guardrail(name):
    """Every reply the product has actually given, offline and from the live
    model, must still pass - a guardrail that fires in normal use gets turned off."""
    text = (config.EVIDENCE_DIR / name).read_text(encoding="utf-8")
    quoted = "\n".join(line[2:] if line.startswith("> ") else "" for line in text.splitlines())
    for paragraph in quoted.split("\n\n"):
        assert gr.check_output(paragraph) == [], paragraph[:120]


def test_a_forbidden_claim_from_the_model_never_reaches_the_seller(monkeypatch):
    monkeypatch.setattr(agent, "run_offline", lambda s, m: {
        "reply": "Great news - your loan is approved and the funds are on the way.",
        "cards": [], "tool_calls": [], "mode": "offline"})
    session = Session(session_id="n6", seller_id="amara-prints", granted_tier=T1_RECOMMEND)
    out = agent.run_turn(session, "Will I run out of cash?")
    assert out["guardrail"]["blocked"] and out["guardrail"]["reason"] == "output_policy"
    assert "approved and the funds" not in out["reply"]


# --- N4: LLM mode cannot hang ---------------------------------------------------

class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_anthropic(monkeypatch, create):
    """Install a stand-in for the anthropic package; return what the client was built with."""
    seen: dict = {}

    class _Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.messages = types.SimpleNamespace(create=create)

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_Client))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    return seen


def test_model_client_is_built_with_a_short_timeout(monkeypatch):
    seen = _fake_anthropic(monkeypatch, lambda **kw: types.SimpleNamespace(
        stop_reason="end_turn", content=[_Block(type="text", text="All fine.")]))
    session = Session(session_id="n4a", seller_id="amara-prints", granted_tier=T1_RECOMMEND)
    out = agent.run_turn(session, "Will I run out of cash?")
    assert out["mode"] == "llm" and out["reply"] == "All fine."
    assert seen["timeout"] == config.LLM_TIMEOUT_SECONDS <= 30
    assert seen["max_retries"] == config.LLM_MAX_RETRIES <= 1


def test_a_network_failure_falls_back_to_offline_mode(monkeypatch):
    def boom(**kw):
        raise TimeoutError("request timed out")
    _fake_anthropic(monkeypatch, boom)
    session = Session(session_id="n4b", seller_id="amara-prints", granted_tier=T1_RECOMMEND)
    out = agent.run_turn(session, "Will I run out of cash?")
    assert out["mode"] == "offline_fallback"
    assert "cash shortfall" in out["reply"]


def test_a_turn_that_runs_too_long_falls_back_instead_of_looping(monkeypatch):
    """The model keeps asking for tools; the turn budget stops it."""
    calls = {"n": 0}

    def keep_calling_tools(**kw):
        calls["n"] += 1
        return types.SimpleNamespace(stop_reason="tool_use", content=[
            _Block(type="tool_use", name="forecast_cashflow", id=f"t{calls['n']}", input={})])
    _fake_anthropic(monkeypatch, keep_calling_tools)
    clock = iter(range(0, 10_000, 30))  # every look at the clock is 30 seconds later
    monkeypatch.setattr(agent.time, "monotonic", lambda: next(clock))
    session = Session(session_id="n4c", seller_id="amara-prints", granted_tier=T1_RECOMMEND)
    out = agent.run_turn(session, "Will I run out of cash?")
    assert out["mode"] == "offline_fallback"
    assert calls["n"] < config.MAX_AGENT_STEPS
