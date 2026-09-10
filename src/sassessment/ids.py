"""Identifier generation and time helpers.

All identifiers are prefixed, sortable and safe to use as path segments and
SQLite keys. Format: ``<PREFIX>-<YYYYMMDD>-<8 hex chars>``.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

_PREFIX_RE = re.compile(r"^[A-Z]{2,8}$")


def utc_now() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp with second precision and ``Z`` suffix."""
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_iso_precise() -> str:
    """ISO-8601 UTC timestamp with millisecond precision."""
    return utc_now().strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc_now().microsecond // 1000:03d}Z"


def short_token(length: int = 8) -> str:
    """Random lowercase-hex token of ``length`` characters."""
    return uuid.uuid4().hex[:length]


def new_id(prefix: str) -> str:
    """Create a new prefixed identifier, e.g. ``EV-20260910-1a2b3c4d``."""
    if not _PREFIX_RE.match(prefix):
        raise ValueError(f"invalid id prefix: {prefix!r}")
    return f"{prefix}-{utc_now().strftime('%Y%m%d')}-{short_token(8)}"


def session_id() -> str:
    return new_id("SES")


def execution_id() -> str:
    return new_id("EXE")


def assessment_id() -> str:
    return new_id("ASMT")


def batch_id(provider_hint: Optional[str] = None) -> str:
    base = new_id("BAT")
    if provider_hint:
        base = f"{base}-{_slug(provider_hint)}"
    return base


def evidence_id() -> str:
    return new_id("EV")


def finding_id() -> str:
    return new_id("FND")


def request_id() -> str:
    return new_id("REQ")


def decision_id() -> str:
    return new_id("DEC")


def checkpoint_id() -> str:
    return new_id("CKP")


def event_id() -> str:
    return new_id("EVT")


def gap_id() -> str:
    return new_id("GAP")


def assumption_id() -> str:
    return new_id("ASM")


def risk_id() -> str:
    return new_id("RSK")


def _slug(text: str, max_len: int = 24) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "batch"
