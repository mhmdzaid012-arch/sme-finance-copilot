"""
FastAPI application.

Route design reflects the security model rather than convenience. In
particular `/api/confirm` is the only path that can execute an action-tier
operation, and it is not reachable by the agent - the model has no HTTP client
and no tool that maps to it. See app/security/permissions.py.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .agent import run_turn
from .security import audit
from .security.permissions import (
    T1_RECOMMEND,
    T2_ACTION,
    Session,
    confirm_action,
    describe_tiers,
)
from .store import dataset_disclaimer, get_seller, list_sellers
from .tools.alerts import generate_alerts
from .tools.analysis import analyse_business
from .tools.financing import match_financing
from .tools.forecast import backtest, forecast_cashflow
from .tools.whatif import WhatIfError, simulate, whatif_options

app = FastAPI(
    title="SME Finance Copilot",
    version="1.0.0",
    description=(
        "An AI finance copilot for e-commerce micro-sellers. Operates entirely on "
        "simulated sandbox data. Not a licensed financial service."
    ),
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# In-memory session store. Adequate for a single-process sandbox demo and
# explicitly listed as a known limitation in docs/SECURITY.md: a real
# deployment needs a shared, expiring, authenticated session store.
SESSIONS: dict[str, Session] = {}


def _session(session_id: str) -> Session:
    s = SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Unknown session. Create one first.")
    return s


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SessionRequest(BaseModel):
    seller_id: str
    # Sessions default to advice-only. Raising to action tier is an explicit,
    # logged choice - and even then nothing executes without confirmation.
    granted_tier: str = Field(default=T1_RECOMMEND)


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=2000)


class ConfirmRequest(BaseModel):
    session_id: str
    token: str
    approved: bool


class FinancingRequest(BaseModel):
    amount: float | None = None
    purpose: str = "working_capital"
    days_needed: int | None = None
    days_until_needed: int | None = None


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "agent_mode": config.agent_mode(),
        "as_of": config.AS_OF.isoformat(),
        "llm_configured": config.anthropic_api_key() is not None,
        "note": (
            "In offline mode the copilot uses a deterministic intent router instead "
            "of a language model. All financial figures come from the tools either "
            "way, so behaviour is identical apart from phrasing."
        ),
        "disclaimer": dataset_disclaimer(),
    }


@app.get("/api/sellers")
def sellers() -> dict:
    return {"sellers": list_sellers(), "disclaimer": dataset_disclaimer()}


@app.get("/api/security/tiers")
def security_tiers() -> dict:
    return describe_tiers()


# ---------------------------------------------------------------------------
# Seller data
# ---------------------------------------------------------------------------

@app.get("/api/seller/{seller_id}")
def seller_detail(seller_id: str) -> dict:
    try:
        ctx = get_seller(seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    return {
        "profile": {k: v for k, v in ctx.profile.items() if k != "derived"},
        "metrics": ctx.metrics,
        "transaction_count": len(ctx.transactions),
    }


@app.get("/api/seller/{seller_id}/forecast")
def seller_forecast(seller_id: str, horizon_days: int = 60) -> dict:
    try:
        ctx = get_seller(seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    return forecast_cashflow(ctx, horizon_days)


@app.get("/api/seller/{seller_id}/alerts")
def seller_alerts(seller_id: str, horizon_days: int = 60) -> dict:
    try:
        ctx = get_seller(seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    return generate_alerts(ctx, forecast_cashflow(ctx, horizon_days))


@app.get("/api/seller/{seller_id}/analysis")
def seller_analysis(seller_id: str) -> dict:
    try:
        ctx = get_seller(seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    return analyse_business(ctx)


@app.post("/api/seller/{seller_id}/financing")
def seller_financing(seller_id: str, req: FinancingRequest) -> dict:
    try:
        ctx = get_seller(seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    return match_financing(
        ctx, amount=req.amount, purpose=req.purpose,
        days_needed=req.days_needed, days_until_needed=req.days_until_needed,
    )


@app.get("/api/seller/{seller_id}/whatif/options")
def seller_whatif_options(seller_id: str) -> dict:
    try:
        ctx = get_seller(seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    return whatif_options(ctx)


@app.post("/api/seller/{seller_id}/whatif")
def seller_whatif(seller_id: str, params: dict) -> dict:
    """Side-by-side projection under changed assumptions. Changes nothing."""
    try:
        ctx = get_seller(seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    try:
        return simulate(ctx, params)
    except WhatIfError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/seller/{seller_id}/backtest")
def seller_backtest(seller_id: str, horizon_days: int = 30) -> dict:
    """Forecast accuracy check against actual history."""
    from datetime import timedelta
    try:
        get_seller(seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    cutoff = config.AS_OF - timedelta(days=horizon_days)
    return backtest(seller_id, cutoff, horizon_days)


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

@app.post("/api/session")
def create_session(req: SessionRequest) -> dict:
    try:
        get_seller(req.seller_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown seller")
    if req.granted_tier not in (T1_RECOMMEND, T2_ACTION):
        raise HTTPException(status_code=400, detail="granted_tier must be T1 or T2.")

    session_id = f"sess-{uuid.uuid4().hex[:12]}"
    SESSIONS[session_id] = Session(
        session_id=session_id, seller_id=req.seller_id, granted_tier=req.granted_tier)
    audit.log_event(session_id, req.seller_id, "session_created",
                    params={"granted_tier": req.granted_tier}, actor="user",
                    mode=config.agent_mode())
    return {
        "session_id": session_id,
        "seller_id": req.seller_id,
        "granted_tier": req.granted_tier,
        "agent_mode": config.agent_mode(),
    }


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    session = _session(req.session_id)
    return run_turn(session, req.message)


@app.post("/api/confirm")
def confirm(req: ConfirmRequest) -> dict:
    """
    Human confirmation surface for action-tier operations.

    This endpoint exists only for the interface. There is no agent tool that
    reaches it, so a prompt-injected model cannot approve its own action.
    """
    session = _session(req.session_id)
    # confirm_action audits its own decision, so there is no logging here -
    # see app/security/permissions.confirm_action.
    return confirm_action(session, req.token, req.approved, actor="user")


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@app.get("/api/audit")
def audit_log(session_id: str = Query(..., min_length=1), limit: int = 200) -> dict:
    """
    A caller sees only its own session's records.

    The full log holds every seller's activity; exposing it to anyone who asks
    would leak one seller's financial questions to another. The session id is
    random and returned only to the client that created the session, so it acts
    as the (demo-grade) credential here - see risk R5 in docs/SECURITY.md.
    """
    _session(session_id)  # 404 for unknown sessions rather than an empty list
    chain = audit.verify_chain()
    return {
        "records": audit.read_log(limit=min(max(limit, 1), 500), session_id=session_id),
        # Integrity status only - no other session's content.
        "chain": {"valid": chain["valid"], "reason": chain["reason"]},
    }


@app.get("/api/audit/verify")
def audit_verify() -> dict:
    return audit.verify_chain()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(404)
def not_found(_request, exc):  # pragma: no cover
    return JSONResponse(status_code=404, content={"detail": str(exc.detail)})
