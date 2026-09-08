from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Severity, SpanStatus, SpanType, TraceStatus
from app.models.security import SecurityFinding
from app.models.trace import Span, Trace
from app.services.ingest_security import persist_findings
from app.services.security import scan_and_redact_object
from app.tests.factories import make_agent, make_project, make_user_with_org


async def _trace_with_span(db: AsyncSession, slug: str) -> tuple[Trace, Span]:
    _, org, _ = await make_user_with_org(
        db, email=f"security-{slug}@x.com", org_slug=f"security-{slug}"
    )
    project = await make_project(db, org, slug=f"project-{slug}")
    agent = await make_agent(db, project, slug=f"agent-{slug}")
    now = datetime.now(timezone.utc)
    trace = Trace(
        organization_id=org.id,
        project_id=project.id,
        agent_id=agent.id,
        external_trace_id=f"trace-{slug}",
        name="security trace",
        status=TraceStatus.RUNNING,
        started_at=now,
        risk_level=Severity.INFO,
    )
    db.add(trace)
    await db.flush()
    span = Span(
        trace_id=trace.id,
        external_span_id=f"span-{slug}",
        name="security span",
        type=SpanType.CUSTOM,
        status=SpanStatus.RUNNING,
        started_at=now,
    )
    db.add(span)
    await db.flush()
    return trace, span


@pytest.mark.asyncio
async def test_persisted_findings_never_contain_raw_sensitive_values(db: AsyncSession):
    trace, span = await _trace_with_span(db, "safe-evidence")
    secrets = [
        "alice@example.com",
        "529.982.247-25",
        "4111111111111111",
        "Bearer synthetic-test-token-123456",
        "sk-abcdefghijklmnopqrstuvwxyzABCDEFGH",
        "supersecret123",
    ]
    result = scan_and_redact_object(
        {
            "email": secrets[0],
            "cpf": secrets[1],
            "card": secrets[2],
            "authorization": secrets[3],
            "api_key": secrets[4],
            "password": secrets[5],
        },
        "input_data",
    )

    created = await persist_findings(db, trace=trace, span=span, matches=result.matches)
    await db.flush()

    assert created
    persisted = (await db.execute(select(SecurityFinding))).scalars().all()
    serialized = json.dumps([
        {
            "title": finding.title,
            "description": finding.description,
            "evidence": finding.evidence,
            "redacted_content": finding.redacted_content,
        }
        for finding in persisted
    ])
    assert all(secret not in serialized for secret in secrets)
    assert all(finding.action_taken == "redact" for finding in persisted)
    assert all(finding.evidence["fingerprint"].startswith("sha256:") for finding in persisted)


@pytest.mark.asyncio
async def test_findings_have_domain_associations_and_raise_trace_risk(db: AsyncSession):
    trace, span = await _trace_with_span(db, "associations")
    scan = scan_and_redact_object(
        {"email": "alice@example.com", "query": "DROP TABLE users;"},
        "tool_call.input_data",
    )

    created = await persist_findings(db, trace=trace, span=span, matches=scan.matches)
    await db.flush()

    assert {(f.finding_type, f.action_taken) for f in created} == {
        ("pii_email", "redact"),
        ("sql_dangerous", "detect"),
    }
    assert all(f.organization_id == trace.organization_id for f in created)
    assert all(f.trace_id == trace.id for f in created)
    assert all(f.span_id == span.id for f in created)
    assert all(f.agent_id == trace.agent_id for f in created)
    assert trace.risk_level == Severity.HIGH


@pytest.mark.asyncio
async def test_findings_are_deduplicated_and_never_lower_trace_risk(db: AsyncSession):
    trace, span = await _trace_with_span(db, "dedupe")
    medium = scan_and_redact_object({"email": "alice@example.com"}, "input_data")
    critical = scan_and_redact_object(
        {"api_key": "sk-abcdefghijklmnopqrstuvwxyzABCDEFGH"}, "input_data"
    )
    other_medium = scan_and_redact_object(
        {"email": "bob@example.com"}, "output_data"
    )

    medium_created = await persist_findings(db, trace=trace, span=span, matches=medium.matches)
    assert medium_created
    assert trace.risk_level == Severity.MEDIUM

    first = await persist_findings(db, trace=trace, span=span, matches=critical.matches)
    assert trace.risk_level == Severity.CRITICAL
    duplicate = await persist_findings(db, trace=trace, span=span, matches=critical.matches)
    lower = await persist_findings(db, trace=trace, span=span, matches=other_medium.matches)
    await db.flush()

    assert len(first) >= 1
    assert duplicate == []
    assert lower
    assert trace.risk_level == Severity.CRITICAL
