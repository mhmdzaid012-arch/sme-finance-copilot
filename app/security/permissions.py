"""
Permission tiers and human-in-the-loop confirmation.

The central design claim of this module: **the agent is structurally incapable
of taking a consequential action on its own.** That is enforced by capability
separation, not by instructing the model to behave well.

Three tiers
-----------
T0_READ       Read simulated data. No side effects.
T1_RECOMMEND  Produce analysis, forecasts, matches, alerts. Still no side effects.
T2_ACTION     Anything with a real-world consequence - submitting a financing
              application, changing payout settings, sharing data with a third
              party. Never executes on the agent's say-so.

How T2 is actually prevented
----------------------------
A T2 tool call does not perform the action. It returns a `pending_confirmation`
containing a single-use token and a plain-language description of exactly what
would happen. Execution requires `confirm_action(token, approved=True)`.

`confirm_action` is deliberately **not registered as an agent tool**. It is
reachable only from the user interface. So even a fully compromised prompt -
one that convinces the model to try to approve its own action - has no tool
with which to do it. The model cannot call it, cannot forge a token (tokens are
random and server-held), and cannot replay one (single-use, expiring, and bound
to a hash of the exact payload).

This is the difference between "we told the model not to" and "the model
cannot".
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field

# --- tiers -----------------------------------------------------------------
T0_READ = "T0_READ"
T1_RECOMMEND = "T1_RECOMMEND"
T2_ACTION = "T2_ACTION"

TIER_RANK = {T0_READ: 0, T1_RECOMMEND: 1, T2_ACTION: 2}

TIER_DESCRIPTIONS = {
    T0_READ: "Read simulated seller data. No side effects.",
    T1_RECOMMEND: "Generate analysis, forecasts and recommendations. No side effects.",
    T2_ACTION: "Actions with real-world consequences. Requires explicit human approval.",
}

# Tokens are short-lived: long enough for a person to read a confirmation
# prompt, short enough that a leaked token is not a standing authority.
TOKEN_TTL_SECONDS = 600


@dataclass(frozen=True)
class ToolPermission:
    name: str
    tier: str
    description: str
    # A one-line, plain-language statement of the consequence, shown to the
    # user at confirmation time. Required for every T2 tool.
    consequence: str = ""


# The registry is the single source of truth for what the agent may attempt.
# Anything not listed here cannot be dispatched at all.
TOOL_REGISTRY: dict[str, ToolPermission] = {
    "get_transactions": ToolPermission(
        "get_transactions", T0_READ,
        "Read the seller's simulated transaction ledger."),
    "analyse_business": ToolPermission(
        "analyse_business", T1_RECOMMEND,
        "Produce a plain-English financial health analysis."),
    "forecast_cashflow": ToolPermission(
        "forecast_cashflow", T1_RECOMMEND,
        "Project the bank balance forward and locate shortfalls."),
    "match_financing": ToolPermission(
        "match_financing", T1_RECOMMEND,
        "Match the seller against illustrative financing products."),
    "generate_alerts": ToolPermission(
        "generate_alerts", T1_RECOMMEND,
        "Turn a forecast into ranked alerts and mitigations."),
    "simulate_whatif": ToolPermission(
        "simulate_whatif", T1_RECOMMEND,
        "Project the balance under changed assumptions. Changes nothing."),
    "submit_financing_application": ToolPermission(
        "submit_financing_application", T2_ACTION,
        "Submit a financing application to a provider.",
        consequence=(
            "Sends this business's financial data to the selected provider and "
            "registers a formal application. In a production system this could "
            "trigger a credit search that affects the business's credit file."
        )),
    "update_payout_settings": ToolPermission(
        "update_payout_settings", T2_ACTION,
        "Change the marketplace payout schedule.",
        consequence=(
            "Alters when money reaches the bank account. Getting this wrong can "
            "directly cause a missed payment."
        )),
    "share_report_with_third_party": ToolPermission(
        "share_report_with_third_party", T2_ACTION,
        "Send a financial report to an external recipient.",
        consequence=(
            "Discloses this business's financial position to a third party. "
            "Irreversible once sent."
        )),
}

# Tools the agent is allowed to see and attempt. Confirmation and audit
# controls are deliberately absent - they are operator surfaces, not agent
# capabilities, and this exclusion is what makes self-approval impossible.
AGENT_INVOCABLE = tuple(
    name for name, p in TOOL_REGISTRY.items()
)


class PermissionError_(Exception):
    """Raised when a call is refused by the tier check."""


@dataclass
class PendingAction:
    token: str
    tool: str
    seller_id: str
    params: dict
    payload_hash: str
    created_at: float
    consequence: str
    expires_at: float
    used: bool = False


@dataclass
class Session:
    """
    One user session. `granted_tier` is the ceiling on what may be attempted;
    it defaults to T1 so that a fresh session can advise but never act.
    """

    session_id: str
    seller_id: str
    granted_tier: str = T1_RECOMMEND
    pending: dict[str, PendingAction] = field(default_factory=dict)

    def tier_allows(self, tool_tier: str) -> bool:
        return TIER_RANK[self.granted_tier] >= TIER_RANK[tool_tier]


def _payload_hash(tool: str, seller_id: str, params: dict) -> str:
    blob = json.dumps(
        {"tool": tool, "seller_id": seller_id, "params": params},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def check_permission(session: Session, tool: str) -> ToolPermission:
    """Resolve a tool name against the registry and the session's tier."""
    perm = TOOL_REGISTRY.get(tool)
    if perm is None:
        raise PermissionError_(
            f"'{tool}' is not a registered tool. Unregistered tools cannot be "
            f"dispatched under any circumstances."
        )
    if not session.tier_allows(perm.tier):
        raise PermissionError_(
            f"'{tool}' requires {perm.tier} but this session is limited to "
            f"{session.granted_tier}."
        )
    return perm


def request_action(session: Session, tool: str, params: dict) -> dict:
    """
    Stage a T2 action. Returns a confirmation request - never a result.

    Note what is *not* returned: any indication that the action happened. The
    only way to move from here to execution is a human calling confirm_action
    with the token, from an interface the agent has no access to.
    """
    perm = check_permission(session, tool)
    if perm.tier != T2_ACTION:
        raise PermissionError_(f"'{tool}' is not an action-tier tool.")

    token = secrets.token_urlsafe(24)
    now = time.time()
    pending = PendingAction(
        token=token,
        tool=tool,
        seller_id=session.seller_id,
        params=params,
        payload_hash=_payload_hash(tool, session.seller_id, params),
        created_at=now,
        consequence=perm.consequence,
        expires_at=now + TOKEN_TTL_SECONDS,
    )
    session.pending[token] = pending

    return {
        "status": "pending_confirmation",
        "tool": tool,
        "requires_tier": T2_ACTION,
        "confirmation_token": token,
        "expires_in_seconds": TOKEN_TTL_SECONDS,
        "what_will_happen": perm.consequence,
        "parameters_for_review": params,
        "how_to_proceed": (
            "This has NOT been done. It will only happen if you explicitly "
            "approve it in the interface. The assistant cannot approve it."
        ),
    }


def confirm_action(session: Session, token: str, approved: bool,
                   actor: str = "user") -> dict:
    """
    Human decision point. Not exposed to the agent - see the module docstring.

    Auditing happens here rather than in the caller, so that no code path can
    execute an action without the decision being recorded. A control that
    depends on every caller remembering to log is not a control.
    """
    # Imported locally to keep the security modules free of import cycles.
    from . import audit

    def _record(result: dict) -> dict:
        audit.log_event(
            session.session_id, session.seller_id, "action_confirmation",
            tool=result.get("tool"), decision=result["status"], actor=actor,
            params={"approved": approved},
            summary=result.get("note") or result.get("reason"),
        )
        return result

    pending = session.pending.get(token)
    if pending is None:
        return _record({"status": "rejected",
                        "reason": "Unknown or already-cleared token."})
    if pending.used:
        return _record({"status": "rejected", "tool": pending.tool,
                        "reason": "This token has already been used."})
    if time.time() > pending.expires_at:
        pending.used = True
        return _record({"status": "rejected", "tool": pending.tool,
                        "reason": "Confirmation expired. Request it again."})

    # Re-verify the payload has not been altered between request and approval,
    # so a user always approves precisely what they were shown.
    if _payload_hash(pending.tool, pending.seller_id, pending.params) != pending.payload_hash:
        pending.used = True
        return _record({"status": "rejected", "tool": pending.tool,
                        "reason": "Payload changed after confirmation was requested."})

    pending.used = True

    if not approved:
        return _record({
            "status": "declined_by_user",
            "tool": pending.tool,
            "actor": actor,
            "note": "No action taken.",
        })

    # In this sandbox, "execution" is recording that a human authorised it.
    # There is no live provider integration by design: the submission surface
    # is exactly where a real deployment would need controls we cannot
    # responsibly demonstrate against third parties.
    return _record({
        "status": "executed_in_sandbox",
        "tool": pending.tool,
        "seller_id": pending.seller_id,
        "params": pending.params,
        "actor": actor,
        "note": (
            "Recorded as an authorised action in the sandbox. No external system "
            "was contacted and no real application was submitted."
        ),
    })


def describe_tiers() -> dict:
    """Used by the UI and the security self-assessment report."""
    return {
        "tiers": [
            {"tier": t, "rank": TIER_RANK[t], "description": TIER_DESCRIPTIONS[t]}
            for t in (T0_READ, T1_RECOMMEND, T2_ACTION)
        ],
        "tools": [
            {"name": p.name, "tier": p.tier, "description": p.description,
             "consequence": p.consequence}
            for p in TOOL_REGISTRY.values()
        ],
        "confirmation_ttl_seconds": TOKEN_TTL_SECONDS,
        "agent_can_confirm_own_actions": False,
        "enforcement": (
            "confirm_action is not in the agent tool registry, so the model has no "
            "capability with which to approve an action. Tokens are server-generated, "
            "single-use, expiring, and bound to a hash of the exact payload shown to "
            "the user."
        ),
    }
