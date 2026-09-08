"""
agentops_monitor — Python SDK for AgentOps Monitor.

Public API:
    AgentOps   — main client
    Trace      — trace context manager (returned by client.trace())
    Span       — span context manager (returned by trace.span())
"""
from agentops_monitor.client import AgentOps
from agentops_monitor._trace import Trace
from agentops_monitor._span import Span
from agentops_monitor.policy import (
    ApprovalRejectedError, ApprovalRequiredError, ApprovalTimeoutError,
    PolicyBlockedError, PolicyDecision, PolicyUnavailableError, ToolPolicyDecision,
)

__all__ = [
    "AgentOps", "Trace", "Span", "PolicyDecision", "ToolPolicyDecision",
    "PolicyBlockedError", "ApprovalRequiredError", "PolicyUnavailableError",
    "ApprovalRejectedError", "ApprovalTimeoutError",
]
__version__ = "0.1.0"
