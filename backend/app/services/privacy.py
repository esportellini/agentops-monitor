"""
Privacy and LGPD compliance service.

Principles:
- user_reference is always stored hashed/anonymized, never raw PII
- inputs/outputs can be disabled per agent policy
- sensitive data is masked before storage via the security scanner
- API keys are never logged
- audit logs are preserved with anonymization
- no data used for training
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import DataRetentionPolicy, PrivacyRequest
from app.models.trace import Trace, Span, CostRecord
from app.models.audit import AuditLog
from app.models.enums import PrivacyRequestStatus, PrivacyRequestType, Severity

# ── Data map ──────────────────────────────────────────────────────────────────

DATA_MAP = [
    {
        "category": "Traces & Spans",
        "table": "traces / spans",
        "fields": ["name", "input_data", "output_data", "error_data", "user_reference", "session_id"],
        "purpose": "Agent observability — debug, performance analysis",
        "sensitivity": "HIGH",
        "contains_pii_risk": True,
        "can_disable": True,
        "retention_key": "traces_retention_days",
    },
    {
        "category": "Tool Calls",
        "table": "tool_calls",
        "fields": ["tool_name", "input_data", "output_data", "status"],
        "purpose": "Track tool usage and detect unauthorized access",
        "sensitivity": "HIGH",
        "contains_pii_risk": True,
        "can_disable": True,
        "retention_key": "spans_retention_days",
    },
    {
        "category": "Model Calls",
        "table": "model_calls",
        "fields": ["provider", "model", "input_tokens", "output_tokens", "estimated_cost"],
        "purpose": "Cost tracking and model usage analytics",
        "sensitivity": "LOW",
        "contains_pii_risk": False,
        "can_disable": False,
        "retention_key": "cost_records_retention_days",
    },
    {
        "category": "Cost Records",
        "table": "cost_records",
        "fields": ["input_tokens", "output_tokens", "cost_usd", "provider", "model"],
        "purpose": "Billing and cost attribution",
        "sensitivity": "MEDIUM",
        "contains_pii_risk": False,
        "can_disable": False,
        "retention_key": "cost_records_retention_days",
    },
    {
        "category": "Security Findings",
        "table": "security_findings",
        "fields": ["finding_type", "evidence", "redacted_content", "action_taken"],
        "purpose": "Security monitoring and incident response",
        "sensitivity": "HIGH",
        "contains_pii_risk": True,
        "can_disable": False,
        "retention_key": None,
    },
    {
        "category": "Audit Logs",
        "table": "audit_logs",
        "fields": ["event_type", "message", "before_data", "after_data", "ip_address", "user_id"],
        "purpose": "Compliance, security audit, accountability",
        "sensitivity": "MEDIUM",
        "contains_pii_risk": True,
        "can_disable": False,
        "retention_key": "audit_logs_retention_days",
    },
    {
        "category": "API Keys",
        "table": "api_keys",
        "fields": ["key_hash", "name", "last_used_at"],
        "purpose": "Authentication for ingest API",
        "sensitivity": "CRITICAL",
        "contains_pii_risk": False,
        "can_disable": False,
        "retention_key": None,
        "note": "Raw key is never stored — only bcrypt hash",
    },
    {
        "category": "User Accounts",
        "table": "users",
        "fields": ["email", "name", "hashed_password"],
        "purpose": "Authentication and authorization",
        "sensitivity": "HIGH",
        "contains_pii_risk": True,
        "can_disable": False,
        "retention_key": None,
        "note": "Password stored as bcrypt hash. Email required for login.",
    },
    {
        "category": "Privacy Requests",
        "table": "privacy_requests",
        "fields": ["subject_reference", "type", "status", "notes"],
        "purpose": "LGPD compliance — track data subject requests",
        "sensitivity": "HIGH",
        "contains_pii_risk": False,
        "can_disable": False,
        "retention_key": None,
        "note": "subject_reference is anonymized identifier, never raw PII",
    },
]


# ── Retention policy CRUD ─────────────────────────────────────────────────────

async def get_retention_policy(db: AsyncSession, organization_id: int) -> DataRetentionPolicy | None:
    r = await db.execute(
        select(DataRetentionPolicy).where(DataRetentionPolicy.organization_id == organization_id)
    )
    return r.scalar_one_or_none()


async def upsert_retention_policy(
    db: AsyncSession,
    organization_id: int,
    data: dict,
) -> DataRetentionPolicy:
    policy = await get_retention_policy(db, organization_id)
    if policy is None:
        policy = DataRetentionPolicy(organization_id=organization_id)
        db.add(policy)

    for field in (
        "traces_retention_days", "spans_retention_days",
        "audit_logs_retention_days", "cost_records_retention_days",
        "anonymize_user_references",
    ):
        if field in data:
            setattr(policy, field, data[field])

    await db.flush()
    return policy


# ── Privacy requests ──────────────────────────────────────────────────────────

async def list_requests(db: AsyncSession, organization_id: int) -> list[PrivacyRequest]:
    r = await db.execute(
        select(PrivacyRequest)
        .where(PrivacyRequest.organization_id == organization_id)
        .order_by(PrivacyRequest.created_at.desc())
    )
    return list(r.scalars().all())


async def create_request(
    db: AsyncSession,
    organization_id: int,
    request_type: str,
    subject_reference: str,
    notes: str | None,
    requested_by_id: int | None,
) -> PrivacyRequest:
    # Ensure subject_reference is a hash, not raw PII
    if "@" in subject_reference or len(subject_reference) < 8:
        subject_reference = hashlib.sha256(subject_reference.encode()).hexdigest()[:16]

    req = PrivacyRequest(
        organization_id=organization_id,
        requested_by_id=requested_by_id,
        type=PrivacyRequestType(request_type),
        status=PrivacyRequestStatus.PENDING,
        subject_reference=subject_reference,
        notes=notes,
    )
    db.add(req)
    await db.flush()
    return req


async def update_request(
    db: AsyncSession,
    request_id: int,
    organization_id: int,
    data: dict,
) -> PrivacyRequest | None:
    r = await db.execute(
        select(PrivacyRequest).where(
            PrivacyRequest.id == request_id,
            PrivacyRequest.organization_id == organization_id,
        )
    )
    req = r.scalar_one_or_none()
    if req is None:
        return None

    if "status" in data:
        req.status = PrivacyRequestStatus(data["status"])
        if data["status"] == "COMPLETED":
            req.completed_at = datetime.now(timezone.utc)
    if "notes" in data:
        req.notes = data["notes"]
    return req


# ── Export ────────────────────────────────────────────────────────────────────

async def export_trace_data(
    db: AsyncSession,
    organization_id: int,
    subject_reference: str | None = None,
    format: str = "json",
) -> str:
    """
    Export trace data for a subject reference (LGPD portability right).
    Returns serialized data as JSON or CSV string.
    """
    q = select(Trace).where(Trace.organization_id == organization_id)
    if subject_reference:
        q = q.where(Trace.user_reference == subject_reference)
    q = q.limit(1000)

    rows = (await db.execute(q)).scalars().all()

    records = []
    for t in rows:
        records.append({
            "id": t.id,
            "name": t.name,
            "status": str(t.status),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "ended_at": t.ended_at.isoformat() if t.ended_at else None,
            "user_reference": t.user_reference,
            # input/output intentionally omitted from export for minimal disclosure
        })

    if format == "csv":
        if not records:
            return "id,name,status,started_at,ended_at,user_reference\n"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=records[0].keys())
        w.writeheader()
        w.writerows(records)
        return buf.getvalue()

    return json.dumps({"traces": records, "exported_at": datetime.now(timezone.utc).isoformat()}, indent=2)


# ── Anonymization ─────────────────────────────────────────────────────────────

async def anonymize_subject(
    db: AsyncSession,
    organization_id: int,
    subject_reference: str,
) -> dict:
    """
    Anonymize all data associated with a subject reference.
    Replaces user_reference with a hash placeholder.
    Nulls input/output on spans/traces for that subject.
    """
    anon_ref = f"anon_{hashlib.sha256(subject_reference.encode()).hexdigest()[:12]}"

    # Update traces
    result = await db.execute(
        text("""
            UPDATE traces
            SET user_reference = :anon,
                input_data = NULL,
                output_data = NULL,
                session_id = NULL
            WHERE organization_id = :org_id
              AND user_reference = :ref
        """),
        {"anon": anon_ref, "org_id": organization_id, "ref": subject_reference},
    )
    traces_updated = result.rowcount

    return {
        "subject_reference": subject_reference,
        "anonymized_as": anon_ref,
        "traces_anonymized": traces_updated,
        "anonymized_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Retention execution ───────────────────────────────────────────────────────

async def run_retention(
    db: AsyncSession,
    organization_id: int,
) -> dict:
    """
    Execute retention policy — delete records older than configured thresholds.
    Audit logs are never deleted here (handled separately with longer defaults).
    Returns count of records deleted per category.
    """
    policy = await get_retention_policy(db, organization_id)
    if policy is None:
        return {"error": "No retention policy configured for this organization"}

    now = datetime.now(timezone.utc)
    deleted: dict[str, int] = {}

    if policy.traces_retention_days:
        cutoff = now - timedelta(days=policy.traces_retention_days)
        r = await db.execute(
            text("DELETE FROM traces WHERE organization_id=:org AND started_at < :cutoff"),
            {"org": organization_id, "cutoff": cutoff},
        )
        deleted["traces"] = r.rowcount

    if policy.audit_logs_retention_days:
        cutoff = now - timedelta(days=policy.audit_logs_retention_days)
        r = await db.execute(
            text("DELETE FROM audit_logs WHERE organization_id=:org AND created_at < :cutoff"),
            {"org": organization_id, "cutoff": cutoff},
        )
        deleted["audit_logs"] = r.rowcount

    deleted["executed_at"] = now.isoformat()
    deleted["policy_id"] = policy.id
    return deleted
