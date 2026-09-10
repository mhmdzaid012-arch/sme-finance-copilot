"""
Append-only audit log with a tamper-evident hash chain.

Every tool dispatch, permission decision, guardrail finding and human
confirmation is recorded. Each record carries the SHA-256 of the previous
record, so removing or editing an entry breaks the chain and can be detected
by `verify_chain()`.

This is not a blockchain and does not need to be. It is the cheapest
construction that makes silent after-the-fact edits detectable, which is the
actual audit requirement: a reviewer can be handed the log and confirm nobody
quietly deleted the interesting line.

The log doubles as the competition's required execution evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .. import config

GENESIS = "0" * 64
_LOCK = threading.Lock()

# Keys whose values are never written to the log in full.
REDACT_KEYS = {"confirmation_token", "token", "api_key", "authorization"}
MAX_VALUE_CHARS = 600


def _log_path() -> Path:
    override = os.environ.get("AUDIT_LOG_PATH")
    if override:
        return Path(override)
    return config.ROOT / "logs" / "audit.jsonl"


def _redact(value):
    """Truncate long values and mask anything token-shaped."""
    if isinstance(value, dict):
        return {
            k: ("***redacted***" if k.lower() in REDACT_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value[:20]]
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        return value[:MAX_VALUE_CHARS] + f"...[truncated {len(value) - MAX_VALUE_CHARS} chars]"
    return value


def _last_hash(path: Path) -> str:
    if not path.exists():
        return GENESIS
    last = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                last = line
    if not last:
        return GENESIS
    try:
        return json.loads(last)["record_hash"]
    except (json.JSONDecodeError, KeyError):
        return GENESIS


def _hash_record(record: dict) -> str:
    blob = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def log_event(session_id: str, seller_id: str, event: str, *,
              tool: str | None = None,
              decision: str | None = None,
              params: dict | None = None,
              summary: str | None = None,
              findings: list | None = None,
              actor: str = "agent",
              mode: str | None = None) -> dict:
    """Append one record and return it (including its hash)."""
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        prev = _last_hash(path)
        body = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "seller_id": seller_id,
            "event": event,
            "tool": tool,
            "decision": decision,
            "actor": actor,
            "mode": mode,
            "params": _redact(params or {}),
            "summary": _redact(summary) if summary else None,
            "findings": _redact(findings or []),
            "prev_hash": prev,
        }
        body["record_hash"] = _hash_record(body)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(body, separators=(",", ":")) + "\n")
    return body


def read_log(limit: int | None = None, session_id: str | None = None) -> list[dict]:
    path = _log_path()
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_id and rec.get("session_id") != session_id:
                continue
            out.append(rec)
    if limit:
        out = out[-limit:]
    return out


def verify_chain() -> dict:
    """
    Recompute the chain and report the first break, if any.

    A reviewer can run this without trusting the application: it depends only
    on the log file's own contents.
    """
    records = read_log()
    expected_prev = GENESIS
    for i, rec in enumerate(records):
        stated_hash = rec.get("record_hash")
        body = {k: v for k, v in rec.items() if k != "record_hash"}
        recomputed = _hash_record(body)
        if rec.get("prev_hash") != expected_prev:
            return {
                "valid": False, "records": len(records), "broken_at": i,
                "reason": "prev_hash does not match the previous record's hash "
                          "(a record was removed, reordered or inserted).",
            }
        if stated_hash != recomputed:
            return {
                "valid": False, "records": len(records), "broken_at": i,
                "reason": "record_hash does not match the record contents "
                          "(a record was edited after being written).",
            }
        expected_prev = stated_hash
    return {"valid": True, "records": len(records), "broken_at": None,
            "reason": "Chain intact."}
