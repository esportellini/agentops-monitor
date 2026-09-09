"""Structured demo reporting with secret leakage guards."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = {"api_key", "authorization", "password", "access_token", "refresh_token", "secret", "token"}


def assert_report_safe(value: Any, forbidden_values: tuple[str, ...] = ()) -> None:
    def walk(item: Any, path: str = "root") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key.lower() in SENSITIVE_KEYS:
                    raise ValueError(f"sensitive report key at {path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")
        elif isinstance(item, str):
            for secret in forbidden_values:
                if secret and secret in item:
                    raise ValueError(f"secret value leaked at {path}")
    walk(value)


def write_report(path: str, report: dict[str, Any], forbidden_values: tuple[str, ...] = ()) -> None:
    assert_report_safe(report, forbidden_values)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
