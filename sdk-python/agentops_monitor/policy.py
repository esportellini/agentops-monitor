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
    approval_id: int | None = None
    external_request_id: str | None = None
    approval_status: str | None = None


class PolicyError(RuntimeError):
    def __init__(self, result: ToolPolicyDecision):
        super().__init__(result.reason)
        self.result = result

    @property
    def approval_id(self) -> int | None:
        return self.result.approval_id

    @property
    def external_request_id(self) -> str | None:
        return self.result.external_request_id

    @property
    def reason_code(self) -> str:
        return self.result.reason_code

    @property
    def status(self) -> str | None:
        return self.result.approval_status


class PolicyBlockedError(PolicyError):
    pass


class ApprovalRequiredError(PolicyError):
    pass


class PolicyUnavailableError(PolicyError):
    pass


class ApprovalRejectedError(PolicyError):
    pass


class ApprovalTimeoutError(PolicyError):
    pass
