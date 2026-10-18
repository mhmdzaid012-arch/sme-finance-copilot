"""Central configuration. No secrets live here."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from a local .env file (git-ignored) into the
    environment. Values already set in the environment win, so a shell
    variable or a test override is never replaced by the file."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
EVIDENCE_DIR = DOCS_DIR / "evidence"

# The sandbox dataset is generated "as of" a fixed date so that every forecast,
# test and piece of submitted evidence is reproducible. Override only for tests.
AS_OF = date(2026, 9, 10)

# --- forecasting parameters (documented in docs/TECHNICAL.md) --------------
SALES_BASELINE_WINDOW_DAYS = 56  # window used for weekday seasonality
TREND_WINDOW_DAYS = 28  # recent vs prior window for growth estimation
TREND_CLAMP = (0.80, 1.30)  # growth factor per 28 days is clamped to this
RECURRING_MIN_OCCURRENCES = 3
RECURRING_MAX_GAP_STDDEV_DAYS = 4.0
DEFAULT_SAFETY_BUFFER = 1500.0

# --- retail seasonality (multiplicative, by calendar month) ---------------
# Mirrors scripts/generate_data.py so the forecaster is consistent with the
# process that produced the history.
SEASONALITY = {
    1: 0.92, 2: 0.95, 3: 1.00, 4: 1.02, 5: 1.03, 6: 1.00,
    7: 0.96, 8: 0.90, 9: 1.04, 10: 1.12, 11: 1.34, 12: 1.42,
}
SEASONALITY_DAMPING = {
    "food_and_beverage": 0.6,
    "electronics_parts": 0.5,
}

# --- LLM configuration -----------------------------------------------------
# The copilot runs in one of two modes:
#   * "llm"     - an Anthropic API key is present; the model plans tool calls.
#   * "offline" - no key present; a deterministic intent router plans instead.
# Offline mode exists so the demo, the tests and the judges' run of this repo
# never depend on a network call or a credential.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_AGENT_STEPS = 6


def anthropic_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def agent_mode() -> str:
    return "llm" if anthropic_api_key() else "offline"
