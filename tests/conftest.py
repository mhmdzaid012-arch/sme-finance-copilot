"""Shared fixtures. Audit logging is redirected to a tmp file per session."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the audit log at a temp file before app modules are imported, so tests
# never append to the repository's own log.
_TMP = Path(tempfile.mkdtemp(prefix="smefc-tests-"))
os.environ["AUDIT_LOG_PATH"] = str(_TMP / "audit.jsonl")

from app.store import get_seller  # noqa: E402

SELLER_IDS = ["amara-prints", "kofi-coffee", "linas-ceramics", "techfix-parts"]


@pytest.fixture(scope="session")
def tmp_audit_dir() -> Path:
    return _TMP


@pytest.fixture(params=SELLER_IDS)
def any_seller(request):
    return get_seller(request.param)


@pytest.fixture
def amara():
    return get_seller("amara-prints")


@pytest.fixture
def lina():
    return get_seller("linas-ceramics")


@pytest.fixture
def techfix():
    return get_seller("techfix-parts")


@pytest.fixture
def kofi():
    return get_seller("kofi-coffee")
