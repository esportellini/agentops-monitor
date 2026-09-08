"""
Internal utilities. Not part of the public API.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("agentops_monitor.internal")


def new_id() -> str:
    """Generate a URL-safe unique ID (UUID4 hex, no dashes)."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def safe_json(obj: Any) -> Any:
    """
    Recursively ensure obj is JSON-serialisable.
    Non-serialisable leaf values are replaced with their repr string.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_json(i) for i in obj]
    try:
        import json
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return repr(obj)


def mask_key(key: str) -> str:
    """Return a redacted version of an API key safe for logging."""
    if not key or len(key) < 12:
        return "***"
    prefix_length = 13 if key.startswith("agom_") else 8
    return f"{key[:prefix_length]}...{key[-4:]}"


def sdk_warn(msg: str, *args: Any) -> None:
    """Log a warning through the SDK logger — never raises."""
    try:
        _log.warning(msg, *args)
    except Exception:
        pass
