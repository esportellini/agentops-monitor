"""Persistence boundary for security findings created by the ingest pipeline."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import Severity
from app.models.security import AgentPolicy, SecurityFinding
from app.models.trace import Span, Trace
from app.services.security import RuleMatch
from app.services.policy import resolve_security_action
from app.services.alerts import (
    SECURITY_FINDING_CREATED,
    RuntimeAlertEvent,
    evaluate_runtime_event,
)

log = get_logger(__name__)

_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def default_action(match: RuleMatch) -> str:
    """Return the phase-default action without consulting AgentPolicy."""
    return "redact" if match.redaction_placeholder else "detect"


def max_severity(current: Severity | str, candidate: Severity | str) -> Severity:
    current_value = current if isinstance(current, Severity) else Severity(current)
    candidate_value = candidate if isinstance(candidate, Severity) else Severity(candidate)
    if _SEVERITY_RANK[candidate_value] > _SEVERITY_RANK[current_value]:
        return candidate_value
    return current_value


def _fingerprint(match: RuleMatch) -> str:
    raw = match.redaction_text or match.matched_text
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _safe_evidence(match: RuleMatch, fingerprint: str, action: str) -> dict[str, object]:
    redacted = match.redaction_placeholder is not None
    return {
        "field_path": match.field,
        "finding_type": match.finding_type,
        "fingerprint": fingerprint,
        "preview": (
            "[BLOCKED_BY_POLICY]" if action == "block"
            else (match.redaction_placeholder or "[REDACTED_BY_POLICY]") if action == "redact"
            else match.redaction_placeholder if redacted
            else match.matched_text[:80]
        ),
        "redacted": redacted,
    }


async def persist_findings(
    db: AsyncSession,
    *,
    trace: Trace,
    matches: list[RuleMatch],
    span: Span | None = None,
    policy: AgentPolicy | None = None,
) -> list[SecurityFinding]:
    """Persist safe, logically deduplicated findings and raise trace risk."""
    created: list[SecurityFinding] = []
    seen: set[tuple[str, str, str]] = set()

    for match in matches:
        fingerprint = _fingerprint(match)
        logical_key = (match.finding_type, match.field, fingerprint)
        if logical_key in seen:
            continue
        seen.add(logical_key)

        candidates = (await db.execute(
            select(SecurityFinding).where(
                SecurityFinding.organization_id == trace.organization_id,
                SecurityFinding.trace_id == trace.id,
                SecurityFinding.span_id == (span.id if span else None),
                SecurityFinding.finding_type == match.finding_type,
            )
        )).scalars().all()
        if any(
            finding.evidence
            and finding.evidence.get("field_path") == match.field
            and finding.evidence.get("fingerprint") == fingerprint
            for finding in candidates
        ):
            continue

        action = resolve_security_action(policy, match.finding_type, default_action(match))
        finding = SecurityFinding(
            organization_id=trace.organization_id,
            trace_id=trace.id,
            span_id=span.id if span else None,
            agent_id=trace.agent_id,
            finding_type=match.finding_type,
            severity=Severity(match.severity),
            title=match.title,
            description=(f"{match.title} in {match.field}" if action in {"redact", "block"} else match.description),
            evidence=_safe_evidence(match, fingerprint, action),
            action_taken=action,
            redacted_content=(
                "[BLOCKED_BY_POLICY]" if action == "block"
                else (match.redaction_placeholder or "[REDACTED_BY_POLICY]") if action == "redact"
                else None
            ),
        )
        db.add(finding)
        created.append(finding)
        trace.risk_level = max_severity(trace.risk_level, match.severity)
        log.info(
            "security.finding.created",
            trace_id=trace.id,
            span_id=span.id if span else None,
            finding_type=match.finding_type,
            severity=match.severity,
            field_path=match.field,
        )

    if created:
        await db.flush()
        now = datetime.now(timezone.utc)
        for finding in created:
            await evaluate_runtime_event(db, RuntimeAlertEvent(
                event_type=SECURITY_FINDING_CREATED,
                organization_id=trace.organization_id,
                project_id=trace.project_id,
                agent_id=trace.agent_id,
                trace_id=trace.id,
                span_id=span.id if span else None,
                source_type="security_finding",
                source_id=str(finding.id),
                occurred_at=finding.created_at or now,
                data={
                    "finding_type": finding.finding_type,
                    "severity": finding.severity.value,
                    "action_taken": finding.action_taken,
                    "policy_id": policy.id if policy else None,
                },
            ))
    return created


async def persist_policy_finding(
    db: AsyncSession,
    *,
    trace: Trace,
    finding_type: str,
    severity: Severity,
    title: str,
    description: str,
    reason_code: str,
    evidence: dict[str, object] | None = None,
    span: Span | None = None,
) -> SecurityFinding | None:
    """Persist a content-free policy violation once per trace/span and reason."""
    safe_evidence = {"reason_code": reason_code, **(evidence or {})}
    candidates = (await db.execute(select(SecurityFinding).where(
        SecurityFinding.organization_id == trace.organization_id,
        SecurityFinding.trace_id == trace.id,
        SecurityFinding.span_id == (span.id if span else None),
        SecurityFinding.finding_type == finding_type,
    ))).scalars().all()
    dedupe_tool = safe_evidence.get("tool_name")
    if any(
        item.evidence
        and item.evidence.get("reason_code") == reason_code
        and item.evidence.get("tool_name") == dedupe_tool
        for item in candidates
    ):
        return None
    finding = SecurityFinding(
        organization_id=trace.organization_id,
        trace_id=trace.id,
        span_id=span.id if span else None,
        agent_id=trace.agent_id,
        finding_type=finding_type,
        severity=severity,
        title=title,
        description=description,
        evidence=safe_evidence,
        action_taken="detect",
    )
    db.add(finding)
    trace.risk_level = max_severity(trace.risk_level, severity)
    await db.flush()
    await evaluate_runtime_event(db, RuntimeAlertEvent(
        event_type=SECURITY_FINDING_CREATED,
        organization_id=trace.organization_id,
        project_id=trace.project_id,
        agent_id=trace.agent_id,
        trace_id=trace.id,
        span_id=span.id if span else None,
        source_type="security_finding",
        source_id=str(finding.id),
        occurred_at=finding.created_at or datetime.now(timezone.utc),
        data={
            "finding_type": finding.finding_type,
            "severity": finding.severity.value,
            "action_taken": finding.action_taken,
            "policy_id": safe_evidence.get("policy_id"),
        },
    ))
    return finding
