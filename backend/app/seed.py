"""
Seed script for the AgentOps Monitor demo organization.

Run with:
    python -m app.seed
or via the CLI wrapper:
    python seed.py

All data is fictional. Passwords are intentionally weak and printed to stdout.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt_mod
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.models.alert import AlertIncident, AlertRule
from app.models.api_key import ApiKey
from app.models.audit import AuditLog
from app.models.enums import (
    AgentStatus,
    AlertIncidentStatus,
    AlertRuleStatus,
    ApiKeyStatus,
    EnvironmentType,
    EvaluationStatus,
    MemberRole,
    ModelCallStatus,
    OrgPlan,
    PrivacyRequestStatus,
    PrivacyRequestType,
    Severity,
    SpanStatus,
    SpanType,
    ToolCallStatus,
    TraceStatus,
)
from app.models.evaluation import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from app.models.organization import Organization, OrganizationMember, User
from app.models.project import Agent, Environment, Project
from app.models.security import SecurityFinding
from app.models.settings import DataRetentionPolicy, SystemSetting
from app.models.trace import (
    CostRecord,
    ModelCall,
    Span,
    ToolCall,
    Trace,
    TraceEvent,
)
from app.services.api_key import generate_api_key

setup_logging()
log = get_logger(__name__)
_pwd_hash = lambda p: _bcrypt_mod.hashpw(p.encode(), _bcrypt_mod.gensalt()).decode()

DEMO_USERS = [
    {"email": "owner@demo.agentops.dev",     "name": "Alex Owner",     "password": "demo-owner-2024",    "role": MemberRole.OWNER},
    {"email": "admin@demo.agentops.dev",     "name": "Blake Admin",    "password": "demo-admin-2024",    "role": MemberRole.ADMIN},
    {"email": "dev@demo.agentops.dev",       "name": "Casey Dev",      "password": "demo-dev-2024",      "role": MemberRole.DEVELOPER},
    {"email": "analyst@demo.agentops.dev",   "name": "Dana Analyst",   "password": "demo-analyst-2024",  "role": MemberRole.ANALYST},
    {"email": "viewer@demo.agentops.dev",    "name": "Ellis Viewer",   "password": "demo-viewer-2024",   "role": MemberRole.VIEWER},
]


def dt(days_ago: float = 0, hours_ago: float = 0, minutes_ago: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)


async def seed(db: AsyncSession) -> None:
    # ── Organization ──────────────────────────────────────────────────────────
    org = Organization(name="Acme AI", slug="acme-ai", plan=OrgPlan.GROWTH)
    db.add(org)
    await db.flush()
    log.info("org created", id=org.id, slug=org.slug)

    # ── Users & Members ───────────────────────────────────────────────────────
    users: dict[str, User] = {}
    for u in DEMO_USERS:
        user = User(
            email=u["email"],
            name=u["name"],
            password_hash=_pwd_hash(u["password"]),
        )
        db.add(user)
        await db.flush()
        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=u["role"],
        )
        db.add(member)
        users[u["role"].value] = user

    owner = users[MemberRole.OWNER.value]
    developer = users[MemberRole.DEVELOPER.value]

    # ── Retention Policy ──────────────────────────────────────────────────────
    db.add(DataRetentionPolicy(
        organization_id=org.id,
        traces_retention_days=90,
        spans_retention_days=90,
        audit_logs_retention_days=365,
    ))

    # ── Projects ──────────────────────────────────────────────────────────────
    proj_assistant = Project(
        organization_id=org.id,
        name="Customer Assistant",
        slug="customer-assistant",
        description="Customer-facing support chatbot with RAG and tool use.",
    )
    proj_analytics = Project(
        organization_id=org.id,
        name="Data Analytics Agent",
        slug="data-analytics",
        description="Internal agent for querying warehouses and generating reports.",
    )
    db.add_all([proj_assistant, proj_analytics])
    await db.flush()

    # ── Environments ──────────────────────────────────────────────────────────
    envs: dict[str, Environment] = {}
    for proj in [proj_assistant, proj_analytics]:
        for name, etype in [
            ("development", EnvironmentType.DEVELOPMENT),
            ("staging", EnvironmentType.STAGING),
            ("production", EnvironmentType.PRODUCTION),
        ]:
            env = Environment(project_id=proj.id, name=name, type=etype)
            db.add(env)
            envs[f"{proj.slug}/{name}"] = env
    await db.flush()

    prod_env = envs["customer-assistant/production"]
    dev_env  = envs["customer-assistant/development"]
    stg_env  = envs["customer-assistant/staging"]

    # ── Agents ────────────────────────────────────────────────────────────────
    agent_support = Agent(
        project_id=proj_assistant.id,
        owner_user_id=developer.id,
        name="Support Bot",
        slug="support-bot",
        description="Handles tier-1 support tickets with knowledge base lookups.",
        version="1.3.0",
        model_provider="openai",
        default_model="gpt-4o",
        status=AgentStatus.ACTIVE,
    )
    agent_escalation = Agent(
        project_id=proj_assistant.id,
        owner_user_id=developer.id,
        name="Escalation Router",
        slug="escalation-router",
        description="Classifies and routes complex tickets to human agents.",
        version="0.9.2",
        model_provider="anthropic",
        default_model="claude-3-5-sonnet-20241022",
        status=AgentStatus.ACTIVE,
    )
    agent_analytics = Agent(
        project_id=proj_analytics.id,
        owner_user_id=developer.id,
        name="Report Generator",
        slug="report-generator",
        description="Generates weekly performance reports from the data warehouse.",
        version="2.0.1",
        model_provider="openai",
        default_model="gpt-4o-mini",
        status=AgentStatus.ACTIVE,
    )
    db.add_all([agent_support, agent_escalation, agent_analytics])
    await db.flush()

    # ── API Keys ──────────────────────────────────────────────────────────────
    raw1, pfx1, hash1 = generate_api_key()
    raw2, pfx2, hash2 = generate_api_key()
    raw3, pfx3, hash3 = generate_api_key()

    key_prod = ApiKey(
        organization_id=org.id,
        project_id=proj_assistant.id,
        created_by_id=owner.id,
        name="Production ingest key",
        key_prefix=pfx1,
        key_hash=hash1,
        status=ApiKeyStatus.ACTIVE,
    )
    key_dev = ApiKey(
        organization_id=org.id,
        project_id=proj_assistant.id,
        created_by_id=developer.id,
        name="Dev ingest key",
        key_prefix=pfx2,
        key_hash=hash2,
        status=ApiKeyStatus.ACTIVE,
    )
    key_revoked = ApiKey(
        organization_id=org.id,
        created_by_id=owner.id,
        revoked_by_id=owner.id,
        name="Old org-wide key (revoked)",
        key_prefix=pfx3,
        key_hash=hash3,
        status=ApiKeyStatus.REVOKED,
        revoked_at=dt(days_ago=10),
    )
    db.add_all([key_prod, key_dev, key_revoked])
    await db.flush()

    # ── Helper: build a trace with spans ─────────────────────────────────────
    async def make_trace(
        *,
        name: str,
        status: TraceStatus,
        agent: Agent,
        env: Environment,
        started_offset_h: float,
        duration_min: float,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        risk: Severity = Severity.INFO,
        session_id: str | None = None,
        user_ref: str | None = None,
    ) -> Trace:
        start = dt(hours_ago=started_offset_h)
        end = start + timedelta(minutes=duration_min)
        trace = Trace(
            organization_id=org.id,
            project_id=agent.project_id,
            agent_id=agent.id,
            environment_id=env.id,
            name=name,
            status=status,
            started_at=start,
            ended_at=end if status != TraceStatus.RUNNING else None,
            duration_ms=int(duration_min * 60 * 1000) if status != TraceStatus.RUNNING else None,
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            total_cost=cost,
            risk_level=risk,
            session_id=session_id,
            user_reference=user_ref,
        )
        db.add(trace)
        await db.flush()
        return trace

    # ── Traces ────────────────────────────────────────────────────────────────
    t1 = await make_trace(
        name="Handle support ticket #8821",
        status=TraceStatus.SUCCESS,
        agent=agent_support,
        env=prod_env,
        started_offset_h=2,
        duration_min=0.8,
        input_tokens=1240,
        output_tokens=310,
        cost=0.00432,
        session_id="sess_8821",
        user_ref="usr_hash_a3f7",
    )
    t2 = await make_trace(
        name="Handle support ticket #8822",
        status=TraceStatus.ERROR,
        agent=agent_support,
        env=prod_env,
        started_offset_h=1.5,
        duration_min=0.3,
        input_tokens=890,
        output_tokens=60,
        cost=0.00128,
        risk=Severity.HIGH,
        session_id="sess_8822",
    )
    t3 = await make_trace(
        name="Handle support ticket #8823",
        status=TraceStatus.BLOCKED,
        agent=agent_support,
        env=prod_env,
        started_offset_h=1,
        duration_min=0.5,
        input_tokens=720,
        output_tokens=0,
        cost=0.0,
        risk=Severity.CRITICAL,
        session_id="sess_8823",
    )
    t4 = await make_trace(
        name="Handle support ticket #8824",
        status=TraceStatus.SUCCESS,
        agent=agent_support,
        env=prod_env,
        started_offset_h=0.5,
        duration_min=1.2,
        input_tokens=1890,
        output_tokens=520,
        cost=0.00712,
        session_id="sess_8824",
    )
    t5 = await make_trace(
        name="Route escalation #221",
        status=TraceStatus.SUCCESS,
        agent=agent_escalation,
        env=stg_env,
        started_offset_h=3,
        duration_min=0.4,
        input_tokens=640,
        output_tokens=180,
        cost=0.00210,
    )
    t6 = await make_trace(
        name="Weekly report — 2024-W22",
        status=TraceStatus.SUCCESS,
        agent=agent_analytics,
        env=envs["data-analytics/production"],
        started_offset_h=24,
        duration_min=4.5,
        input_tokens=12400,
        output_tokens=3200,
        cost=0.04120,
    )
    t7 = await make_trace(
        name="Handle support ticket #8825 (running)",
        status=TraceStatus.RUNNING,
        agent=agent_support,
        env=prod_env,
        started_offset_h=0.05,
        duration_min=0,
        input_tokens=0,
        output_tokens=0,
        cost=0,
    )
    t8 = await make_trace(
        name="Staging smoke test",
        status=TraceStatus.SUCCESS,
        agent=agent_support,
        env=stg_env,
        started_offset_h=6,
        duration_min=0.2,
        input_tokens=200,
        output_tokens=50,
        cost=0.00030,
    )

    # ── Spans (hierarchical) for t1 ──────────────────────────────────────────
    def span(
        trace: Trace,
        parent: Span | None,
        name: str,
        stype: SpanType,
        status: SpanStatus,
        offset_s: float,
        dur_ms: int,
        inp: dict | None = None,
        out: dict | None = None,
        err: dict | None = None,
    ) -> Span:
        start = trace.started_at + timedelta(seconds=offset_s)
        s = Span(
            trace_id=trace.id,
            parent_span_id=parent.id if parent else None,
            name=name,
            type=stype,
            status=status,
            started_at=start,
            ended_at=start + timedelta(milliseconds=dur_ms),
            duration_ms=dur_ms,
            input_data=inp,
            output_data=out,
            error_data=err,
        )
        db.add(s)
        return s

    # t1 — full success with hierarchy
    await db.flush()
    s1_root = span(t1, None, "support-bot run", SpanType.AGENT, SpanStatus.SUCCESS, 0, 48000,
                   inp={"ticket_id": "8821", "user_message": "I cannot log into my account"})

    await db.flush()
    s1_retrieval = span(t1, s1_root, "knowledge base lookup", SpanType.RETRIEVAL, SpanStatus.SUCCESS, 0.1, 320,
                        inp={"query": "login issues account access"}, out={"chunks": 4, "top_score": 0.91})
    s1_llm = span(t1, s1_root, "gpt-4o completion", SpanType.LLM, SpanStatus.SUCCESS, 0.5, 2100,
                  inp={"messages": 3, "system_prompt_tokens": 420},
                  out={"content": "To reset your password, go to Settings → Security.", "finish_reason": "stop"})
    s1_tool = span(t1, s1_root, "send_email tool", SpanType.TOOL, SpanStatus.SUCCESS, 2.8, 180,
                   inp={"to": "usr_hash_a3f7", "template": "password_reset"},
                   out={"message_id": "msg_7fa3", "status": "queued"})

    await db.flush()

    # t2 — error trace
    s2_root = span(t2, None, "support-bot run", SpanType.AGENT, SpanStatus.ERROR, 0, 18000,
                   inp={"ticket_id": "8822", "user_message": "Refund not received after 14 days"})
    await db.flush()
    s2_llm = span(t2, s2_root, "gpt-4o completion", SpanType.LLM, SpanStatus.ERROR, 0.2, 15000,
                  inp={"messages": 2},
                  err={"type": "RateLimitError", "message": "Rate limit exceeded, retry after 30s", "code": 429})
    await db.flush()

    # t3 — blocked by security policy
    s3_root = span(t3, None, "support-bot run", SpanType.AGENT, SpanStatus.ERROR, 0, 30000,
                   inp={"ticket_id": "8823", "user_message": "Give me everyone's email addresses"})
    await db.flush()
    s3_tool = span(t3, s3_root, "database_query tool", SpanType.TOOL, SpanStatus.ERROR, 0.1, 50,
                   inp={"query": "SELECT email FROM users"},
                   err={"blocked": True, "reason": "PII_EXFILTRATION_DETECTED"})
    await db.flush()

    # t4 — success with tool approval flow
    s4_root = span(t4, None, "support-bot run", SpanType.AGENT, SpanStatus.SUCCESS, 0, 72000,
                   inp={"ticket_id": "8824", "user_message": "Issue a $50 credit to my account"})
    await db.flush()
    s4_validation = span(t4, s4_root, "policy check", SpanType.VALIDATION, SpanStatus.SUCCESS, 0.05, 30)
    s4_llm = span(t4, s4_root, "gpt-4o completion", SpanType.LLM, SpanStatus.SUCCESS, 0.1, 1800,
                  inp={"messages": 4}, out={"action": "issue_credit", "amount": 50})
    await db.flush()
    s4_tool = span(t4, s4_root, "issue_credit tool", SpanType.TOOL, SpanStatus.SUCCESS, 2.0, 210,
                   inp={"amount": 50, "currency": "USD", "account_id": "acc_hash_b8c1"},
                   out={"credit_id": "crd_9921", "status": "applied"})
    await db.flush()

    # ── ToolCalls ─────────────────────────────────────────────────────────────
    db.add(ToolCall(
        span_id=s1_tool.id,
        tool_name="send_email",
        input_data={"to": "usr_hash_a3f7", "template": "password_reset"},
        output_data={"message_id": "msg_7fa3", "status": "queued"},
        status=ToolCallStatus.SUCCESS,
        duration_ms=180,
        requires_approval=False,
    ))
    db.add(ToolCall(
        span_id=s3_tool.id,
        tool_name="database_query",
        input_data={"query": "SELECT email FROM users"},
        output_data=None,
        status=ToolCallStatus.BLOCKED,
        duration_ms=50,
        requires_approval=True,
        blocked_reason="PII exfiltration pattern detected: SELECT on users.email without WHERE clause",
    ))
    db.add(ToolCall(
        span_id=s4_tool.id,
        tool_name="issue_credit",
        input_data={"amount": 50, "currency": "USD", "account_id": "acc_hash_b8c1"},
        output_data={"credit_id": "crd_9921", "status": "applied"},
        status=ToolCallStatus.SUCCESS,
        duration_ms=210,
        requires_approval=True,
        approved_by_id=owner.id,
    ))
    await db.flush()

    # ── ModelCalls ────────────────────────────────────────────────────────────
    mc1 = ModelCall(
        span_id=s1_llm.id,
        provider="openai",
        model="gpt-4o",
        input_tokens=1240,
        output_tokens=310,
        estimated_cost=0.00432,
        latency_ms=2100,
        temperature=0.2,
        status=ModelCallStatus.SUCCESS,
    )
    mc2 = ModelCall(
        span_id=s2_llm.id,
        provider="openai",
        model="gpt-4o",
        input_tokens=890,
        output_tokens=0,
        estimated_cost=0.0,
        latency_ms=15000,
        temperature=0.2,
        status=ModelCallStatus.RATE_LIMITED,
    )
    mc3 = ModelCall(
        span_id=s4_llm.id,
        provider="openai",
        model="gpt-4o",
        input_tokens=1890,
        output_tokens=520,
        estimated_cost=0.00712,
        latency_ms=1800,
        temperature=0.1,
        status=ModelCallStatus.SUCCESS,
    )
    db.add_all([mc1, mc2, mc3])
    await db.flush()

    # ── CostRecords ───────────────────────────────────────────────────────────
    db.add(CostRecord(
        organization_id=org.id, trace_id=t1.id, model_call_id=mc1.id,
        provider="openai", model="gpt-4o",
        input_tokens=1240, output_tokens=310, cost_usd=0.00432,
        recorded_at=t1.ended_at,
    ))
    db.add(CostRecord(
        organization_id=org.id, trace_id=t4.id, model_call_id=mc3.id,
        provider="openai", model="gpt-4o",
        input_tokens=1890, output_tokens=520, cost_usd=0.00712,
        recorded_at=t4.ended_at,
    ))
    db.add(CostRecord(
        organization_id=org.id, trace_id=t6.id, model_call_id=None,
        provider="openai", model="gpt-4o-mini",
        input_tokens=12400, output_tokens=3200, cost_usd=0.04120,
        recorded_at=t6.ended_at,
    ))

    # ── TraceEvents ───────────────────────────────────────────────────────────
    db.add(TraceEvent(
        trace_id=t1.id, span_id=s1_retrieval.id,
        event_type="retrieval.completed",
        severity=Severity.INFO,
        message="Retrieved 4 knowledge base chunks (top score 0.91)",
        created_at=t1.started_at + timedelta(seconds=0.43),
    ))
    db.add(TraceEvent(
        trace_id=t2.id, span_id=s2_llm.id,
        event_type="llm.rate_limit",
        severity=Severity.HIGH,
        message="OpenAI rate limit hit on gpt-4o. Trace aborted after 15s wait.",
        metadata_={"retry_after": 30, "model": "gpt-4o"},
        created_at=t2.started_at + timedelta(seconds=15.2),
    ))
    db.add(TraceEvent(
        trace_id=t3.id, span_id=s3_tool.id,
        event_type="security.policy_violation",
        severity=Severity.CRITICAL,
        message="Tool call blocked: PII exfiltration pattern in database_query",
        metadata_={"tool": "database_query", "policy": "pii_protection_v2"},
        created_at=t3.started_at + timedelta(seconds=0.15),
    ))
    db.add(TraceEvent(
        trace_id=t4.id, span_id=s4_tool.id,
        event_type="tool.approval_granted",
        severity=Severity.MEDIUM,
        message="High-value credit issuance approved by owner",
        metadata_={"amount": 50, "approved_by": owner.email},
        created_at=t4.started_at + timedelta(seconds=35),
    ))

    # ── SecurityFindings ──────────────────────────────────────────────────────
    db.add(SecurityFinding(
        organization_id=org.id,
        trace_id=t3.id,
        span_id=s3_tool.id,
        finding_type="PII_EXFILTRATION",
        severity=Severity.CRITICAL,
        title="Attempted bulk PII extraction via database_query tool",
        description=(
            "Agent attempted to execute 'SELECT email FROM users' without any WHERE clause. "
            "This would have returned all user emails. Request was blocked by policy pii_protection_v2."
        ),
        evidence={
            "query": "SELECT email FROM users",
            "tool": "database_query",
            "session_id": t3.session_id,
        },
    ))
    db.add(SecurityFinding(
        organization_id=org.id,
        trace_id=t2.id,
        finding_type="EXCESSIVE_RETRY",
        severity=Severity.MEDIUM,
        title="Agent did not handle rate limit gracefully",
        description="Rate limit error from OpenAI was not caught; agent hung for 15s before terminating.",
        evidence={"latency_ms": 15000, "model": "gpt-4o"},
    ))

    # ── AlertRules ────────────────────────────────────────────────────────────
    rule_error_rate = AlertRule(
        organization_id=org.id,
        project_id=proj_assistant.id,
        created_by_id=owner.id,
        name="High error rate",
        description="Triggers when trace error rate exceeds 10% over 15 minutes.",
        condition={"metric": "error_rate", "op": "gt", "threshold": 0.10, "window_minutes": 15},
        severity=Severity.HIGH,
        status=AlertRuleStatus.ACTIVE,
        notification_channels={"slack": "#alerts-ai", "email": ["admin@demo.agentops.dev"]},
    )
    rule_cost = AlertRule(
        organization_id=org.id,
        created_by_id=owner.id,
        name="Daily cost spike",
        description="Triggers when estimated daily cost exceeds $10.",
        condition={"metric": "daily_cost_usd", "op": "gt", "threshold": 10.0},
        severity=Severity.MEDIUM,
        status=AlertRuleStatus.ACTIVE,
        notification_channels={"email": ["owner@demo.agentops.dev"]},
    )
    rule_blocked = AlertRule(
        organization_id=org.id,
        project_id=proj_assistant.id,
        created_by_id=owner.id,
        name="Security block detected",
        description="Triggers immediately when any trace is blocked by a security policy.",
        condition={"metric": "trace_status", "value": "BLOCKED"},
        severity=Severity.CRITICAL,
        status=AlertRuleStatus.ACTIVE,
        notification_channels={"slack": "#security"},
    )
    db.add_all([rule_error_rate, rule_cost, rule_blocked])
    await db.flush()

    # ── AlertIncidents ────────────────────────────────────────────────────────
    db.add(AlertIncident(
        rule_id=rule_blocked.id,
        status=AlertIncidentStatus.OPEN,
        triggered_at=t3.started_at + timedelta(seconds=1),
        context={"trace_id": t3.id, "finding": "PII_EXFILTRATION"},
    ))
    db.add(AlertIncident(
        rule_id=rule_error_rate.id,
        status=AlertIncidentStatus.RESOLVED,
        triggered_at=t2.started_at,
        resolved_at=t2.started_at + timedelta(hours=1),
        resolved_by_id=owner.id,
        context={"error_rate": 0.50, "window": "15m"},
    ))

    # ── Evaluation Dataset ────────────────────────────────────────────────────
    dataset = EvaluationDataset(
        organization_id=org.id,
        project_id=proj_assistant.id,
        created_by_id=developer.id,
        name="Support Bot — Q1 2024 golden set",
        description="100 manually labelled support interactions.",
    )
    db.add(dataset)
    await db.flush()

    cases_data = [
        ({"message": "How do I reset my password?"}, {"intent": "password_reset", "should_escalate": False}),
        ({"message": "I was charged twice last month"}, {"intent": "billing_dispute", "should_escalate": True}),
        ({"message": "Cancel my subscription"}, {"intent": "cancellation", "should_escalate": False}),
    ]
    cases = []
    for inp, exp in cases_data:
        c = EvaluationCase(dataset_id=dataset.id, input_data=inp, expected_output=exp)
        db.add(c)
        cases.append(c)
    await db.flush()

    run = EvaluationRun(
        organization_id=org.id,
        dataset_id=dataset.id,
        triggered_by_id=developer.id,
        name="Run #1 — gpt-4o baseline",
        status=EvaluationStatus.COMPLETED,
        started_at=dt(days_ago=3),
        ended_at=dt(days_ago=3, hours_ago=-1),
        total_cases=3, passed_cases=2, pass_rate=0.67, average_score=0.84,
    )
    db.add(run)
    await db.flush()

    results = [
        (cases[0], True, 0.97, {"intent": "password_reset", "should_escalate": False}, None),
        (cases[1], True, 0.88, {"intent": "billing_dispute", "should_escalate": True}, None),
        (cases[2], False, 0.61, {"intent": "general_inquiry", "should_escalate": False},
         "Agent misclassified cancellation intent as general inquiry."),
    ]
    for case, passed, score, actual, feedback in results:
        db.add(EvaluationResult(
            run_id=run.id,
            case_id=case.id,
            passed=passed,
            score=score,
            actual_output=actual,
            evaluator_details=feedback,
        ))

    # ── AuditLogs ─────────────────────────────────────────────────────────────
    audit_entries = [
        (owner, "org.created",      "organization", str(org.id),     Severity.INFO,
         "Organization 'Acme AI' created"),
        (owner, "api_key.created",  "api_key",      str(key_prod.id), Severity.LOW,
         f"API key '{key_prod.name}' created for project customer-assistant"),
        (owner, "api_key.revoked",  "api_key",      str(key_revoked.id), Severity.MEDIUM,
         f"API key '{key_revoked.name}' revoked"),
        (owner, "member.invited",   "user",         str(developer.id), Severity.LOW,
         f"User {developer.email} invited as DEVELOPER"),
        (None,  "security.finding", "trace",        str(t3.id),       Severity.CRITICAL,
         "PII exfiltration attempt blocked in trace #8823"),
        (owner, "alert.resolved",   "alert_rule",   str(rule_error_rate.id), Severity.INFO,
         "Alert 'High error rate' incident resolved manually"),
    ]
    for user, etype, ent_type, ent_id, sev, msg in audit_entries:
        db.add(AuditLog(
            organization_id=org.id,
            user_id=user.id if user else None,
            event_type=etype,
            entity_type=ent_type,
            entity_id=ent_id,
            severity=sev,
            message=msg,
            created_at=dt(days_ago=1),
        ))

    # ── SystemSettings ────────────────────────────────────────────────────────
    db.add(SystemSetting(
        key="platform.maintenance_mode",
        value={"enabled": False},
        description="When enabled, the platform rejects all ingest traffic.",
        is_public=True,
    ))
    db.add(SystemSetting(
        key="platform.max_traces_per_org_per_day",
        value={"limit": 100000},
        description="Hard cap on ingested traces per org per 24h window.",
        is_public=False,
    ))

    await db.commit()

    # ── Print credentials ─────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  AgentOps Monitor — Demo seed complete")
    print("=" * 62)
    print(f"\n  Organization : Acme AI  (slug: acme-ai)")
    print(f"\n  {'Role':<12}  {'Email':<38}  {'Password'}")
    print(f"  {'-'*12}  {'-'*38}  {'-'*20}")
    for u in DEMO_USERS:
        print(f"  {u['role'].value:<12}  {u['email']:<38}  {u['password']}")
    print(f"\n  API Keys (shown once):")
    print(f"    Production : {raw1}")
    print(f"    Dev        : {raw2}")
    print(f"    (revoked)  : {raw3}")
    print("=" * 62 + "\n")


async def main() -> None:
    _db_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(_db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        await seed(db)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
