"""Typed policy decisions and enforcement errors."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ToolPolicyDecision:
    decision: PolicyDecision
    reason_code: str
    reason: str
    policy_id: int | None = None
    limits: dict[str, Any] = field(default_factory=dict)


class PolicyError(RuntimeError):
    def __init__(self, result: ToolPolicyDecision):
        super().__init__(result.reason)
        self.result = result


class PolicyBlockedError(PolicyError):
    pass


class ApprovalRequiredError(PolicyError):
    pass


class PolicyUnavailableError(PolicyError):
    pass
