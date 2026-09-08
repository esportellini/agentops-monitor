"""Authoritative AgentPolicy evaluation shared by preflight and ingest."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from urllib.parse import urlparse

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import AgentPolicy
from app.models.trace import ModelCall, Span, Trace
from app.services.pricing import PRICED, UNPRICED
from app.services.security import (
    FINDING_API_KEY,
    FINDING_BEARER_TOKEN,
    FINDING_CREDENTIAL,
    FINDING_PII_CARD,
    FINDING_PII_CPF,
    FINDING_PII_EMAIL,
    FINDING_PII_PHONE,
    FINDING_PROMPT_INJECTION,
    StructuredScanResult,
)


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class LimitState(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    OK = "OK"
    EXCEEDED = "EXCEEDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TraceLimitState:
    token_state: LimitState
    cost_state: LimitState
    total_tokens: int
    known_cost_usd: Decimal
    unpriced_model_calls: int


@dataclass(frozen=True)
class ToolPolicyResult:
    decision: PolicyDecision
    reason_code: str
    reason: str
    policy_id: int | None
    limits: TraceLimitState


_PII_TYPES = {
    FINDING_PII_EMAIL, FINDING_PII_PHONE, FINDING_PII_CPF, FINDING_PII_CARD,
}
_SECRET_TYPES = {FINDING_API_KEY, FINDING_BEARER_TOKEN, FINDING_CREDENTIAL}
_ACTIONS = {"detect", "redact", "alert", "block"}


def _names(values: list | None) -> set[str]:
    return {str(value).strip().lower() for value in (values or []) if str(value).strip()}


def normalize_policy_list(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return sorted(_names(values))


async def resolve_agent_policy(
    db: AsyncSession, organization_id: int, agent_id: int | None
) -> AgentPolicy | None:
    if agent_id is None:
        return None
    return await db.scalar(select(AgentPolicy).where(
        AgentPolicy.organization_id == organization_id,
        AgentPolicy.agent_id == agent_id,
        AgentPolicy.active.is_(True),
    ))


def resolve_security_action(
    policy: AgentPolicy | None, finding_type: str, baseline_action: str
) -> str:
    if policy is None:
        return baseline_action
    if finding_type in _PII_TYPES:
        action = policy.pii_action
    elif finding_type in _SECRET_TYPES:
        action = policy.secret_action
    elif finding_type == FINDING_PROMPT_INJECTION:
        action = policy.injection_action
    else:
        return baseline_action
    return action if action in _ACTIONS else baseline_action


def apply_security_actions(
    scan: StructuredScanResult, policy: AgentPolicy | None, field_path: str
) -> StructuredScanResult:
    """Replace leaves governed by a block action; baseline redaction remains intact."""
    resolved = [
        (match, resolve_security_action(
            policy, match.finding_type, "redact" if match.redaction_placeholder else "detect"
        ))
        for match in scan.matches
    ]
    blocked_paths = {match.field for match, action in resolved if action == "block"}
    redacted_paths = {
        match.field for match, action in resolved
        if action == "redact" and match.redaction_placeholder is None
        and match.field not in blocked_paths
    }

    def visit(value: object, path: str) -> object:
        if path in blocked_paths:
            return "[BLOCKED_BY_POLICY]"
        if path in redacted_paths:
            return "[REDACTED_BY_POLICY]"
        if isinstance(value, dict):
            return {key: visit(child, f"{path}.{key}") for key, child in value.items()}
        if isinstance(value, list):
            return [visit(child, f"{path}[{index}]") for index, child in enumerate(value)]
        return value

    sanitized = visit(scan.sanitized, field_path)
    return StructuredScanResult(sanitized=sanitized, matches=scan.matches)


def _domain(value: str) -> str | None:
    raw = value.strip()
    if not raw or any(ch.isspace() for ch in raw):
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    try:
        host = parsed.hostname
        if parsed.port is not None:
            pass
    except ValueError:
        return None
    if not host or host.startswith(".") or host.endswith("."):
        return None
    host = host.lower().removeprefix("www.")
    if ".." in host or any(not part for part in host.split(".")):
        return None
    return host


def _domain_matches(host: str, rule: str) -> bool:
    normalized = (_domain(rule) or "").lower()
    return bool(normalized) and (host == normalized or host.endswith(f".{normalized}"))


def evaluate_tool(policy: AgentPolicy | None, tool_name: str) -> tuple[PolicyDecision, str, str]:
    if policy is None:
        return PolicyDecision.ALLOW, "NO_ACTIVE_POLICY", "No active policy applies"
    tool = tool_name.strip().lower()
    if not tool:
        return PolicyDecision.BLOCK, "INVALID_TOOL_NAME", "Tool name is required"
    if tool in _names(policy.blocked_tools):
        return PolicyDecision.BLOCK, "TOOL_BLOCKED", "Tool is explicitly blocked"
    allowed = _names(policy.allowed_tools)
    if allowed and tool not in allowed:
        return PolicyDecision.BLOCK, "TOOL_NOT_ALLOWED", "Tool is outside the allowlist"
    if tool in _names(policy.tools_requiring_approval):
        return PolicyDecision.REQUIRE_APPROVAL, "TOOL_REQUIRES_APPROVAL", "Tool requires approval"
    return PolicyDecision.ALLOW, "POLICY_ALLOWED", "Tool is allowed"


def evaluate_domain(policy: AgentPolicy | None, target_url: str | None) -> tuple[bool, str, str]:
    if policy is None or target_url is None:
        return True, "DOMAIN_NOT_CHECKED", "No target domain restriction applies"
    host = _domain(target_url)
    if host is None:
        return False, "INVALID_TARGET_URL", "Target URL is malformed"
    if any(_domain_matches(host, rule) for rule in (policy.blocked_domains or [])):
        return False, "DOMAIN_BLOCKED", "Target domain is explicitly blocked"
    allowed = policy.allowed_domains or []
    if allowed and not any(_domain_matches(host, rule) for rule in allowed):
        return False, "DOMAIN_NOT_ALLOWED", "Target domain is outside the allowlist"
    return True, "DOMAIN_ALLOWED", "Target domain is allowed"


async def evaluate_trace_limits(
    db: AsyncSession, trace: Trace, policy: AgentPolicy | None
) -> TraceLimitState:
    row = (await db.execute(select(
        func.coalesce(func.sum(ModelCall.input_tokens + ModelCall.output_tokens), 0),
        func.coalesce(func.sum(case((ModelCall.pricing_status == PRICED, ModelCall.estimated_cost), else_=0)), 0),
        func.coalesce(func.sum(case((ModelCall.pricing_status == UNPRICED, 1), else_=0)), 0),
    ).join(Span, Span.id == ModelCall.span_id).where(Span.trace_id == trace.id))).one()
    tokens, known_cost, unpriced = int(row[0]), Decimal(str(row[1])), int(row[2])
    if policy is None or policy.max_tokens_per_trace is None:
        token_state = LimitState.NOT_CONFIGURED
    else:
        token_state = LimitState.EXCEEDED if tokens > policy.max_tokens_per_trace else LimitState.OK
    if policy is None or policy.max_cost_per_trace_usd is None:
        cost_state = LimitState.NOT_CONFIGURED
    elif known_cost > Decimal(str(policy.max_cost_per_trace_usd)):
        cost_state = LimitState.EXCEEDED
    elif unpriced:
        cost_state = LimitState.UNKNOWN
    else:
        cost_state = LimitState.OK
    return TraceLimitState(token_state, cost_state, tokens, known_cost, unpriced)


async def evaluate_tool_preflight(
    db: AsyncSession, trace: Trace, tool_name: str, target_url: str | None
) -> ToolPolicyResult:
    policy = await resolve_agent_policy(db, trace.organization_id, trace.agent_id)
    limits = await evaluate_trace_limits(db, trace, policy)
    tool_decision, tool_code, tool_reason = evaluate_tool(policy, tool_name)
    domain_allowed, domain_code, domain_reason = evaluate_domain(policy, target_url)
    if tool_decision == PolicyDecision.BLOCK:
        return ToolPolicyResult(tool_decision, tool_code, tool_reason, policy.id if policy else None, limits)
    if not domain_allowed:
        return ToolPolicyResult(PolicyDecision.BLOCK, domain_code, domain_reason, policy.id if policy else None, limits)
    if limits.token_state == LimitState.EXCEEDED:
        return ToolPolicyResult(PolicyDecision.BLOCK, "TRACE_TOKEN_LIMIT_EXCEEDED", "Trace token limit is exceeded", policy.id if policy else None, limits)
    if limits.cost_state == LimitState.EXCEEDED:
        return ToolPolicyResult(PolicyDecision.BLOCK, "TRACE_COST_LIMIT_EXCEEDED", "Trace cost limit is exceeded", policy.id if policy else None, limits)
    if tool_decision == PolicyDecision.REQUIRE_APPROVAL:
        return ToolPolicyResult(tool_decision, tool_code, tool_reason, policy.id if policy else None, limits)
    return ToolPolicyResult(PolicyDecision.ALLOW, tool_code, tool_reason, policy.id if policy else None, limits)
