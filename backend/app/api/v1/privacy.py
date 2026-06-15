"""
Privacy and LGPD API.
All endpoints are org-scoped and ANALYST+ role required for mutations.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, require_analyst, require_org_member
from app.db.session import get_db
from app.services import audit as audit_svc
from app.services import privacy as privacy_svc
from app.models.enums import Severity

router = APIRouter(prefix="/organizations/{org_id}/privacy", tags=["privacy"])


@router.get("/data-map")
async def data_map(ctx: OrgContext = Depends(require_org_member)):
    """Return the platform data map — categories, fields, purposes, sensitivity."""
    return {"items": privacy_svc.DATA_MAP}


@router.get("/retention-policies")
async def get_retention_policy(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    policy = await privacy_svc.get_retention_policy(db, ctx.org_id)
    if policy is None:
        return {
            "id": None, "organization_id": ctx.org_id,
            "traces_retention_days": 90, "spans_retention_days": 90,
            "audit_logs_retention_days": 365, "cost_records_retention_days": None,
            "anonymize_user_references": True,
            "note": "No custom policy — defaults shown",
        }
    return _policy_out(policy)


@router.post("/retention-policies", status_code=201)
async def create_retention_policy(
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    policy = await privacy_svc.upsert_retention_policy(db, ctx.org_id, payload)
    await audit_svc.write(
        db, organization_id=ctx.org_id, user_id=ctx.user_id,
        event_type="privacy.retention_policy.created",
        message="Retention policy created/updated",
        after_data=payload, severity=Severity.MEDIUM,
    )
    await db.commit()
    return _policy_out(policy)


@router.patch("/retention-policies/{policy_id}")
async def update_retention_policy(
    policy_id: int,
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    policy = await privacy_svc.upsert_retention_policy(db, ctx.org_id, payload)
    await audit_svc.write(
        db, organization_id=ctx.org_id, user_id=ctx.user_id,
        event_type="privacy.retention_policy.updated",
        message="Retention policy updated",
        after_data=payload, severity=Severity.MEDIUM,
    )
    await db.commit()
    return _policy_out(policy)


@router.get("/requests")
async def list_requests(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    reqs = await privacy_svc.list_requests(db, ctx.org_id)
    return {"items": [_req_out(r) for r in reqs]}


@router.post("/requests", status_code=201)
async def create_request(
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    req_type = payload.get("type")
    if req_type not in ("EXPORT", "ANONYMIZE", "DELETE", "ACCESS"):
        raise HTTPException(422, "type must be EXPORT | ANONYMIZE | DELETE | ACCESS")

    req = await privacy_svc.create_request(
        db, ctx.org_id,
        request_type=req_type,
        subject_reference=payload["subject_reference"],
        notes=payload.get("notes"),
        requested_by_id=ctx.user_id,
    )
    await audit_svc.write(
        db, organization_id=ctx.org_id, user_id=ctx.user_id,
        event_type="privacy.request.created",
        message=f"Privacy request ({req_type}) created for subject {req.subject_reference}",
        severity=Severity.MEDIUM,
    )
    await db.commit()
    return _req_out(req)


@router.patch("/requests/{request_id}")
async def update_request(
    request_id: int,
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    req = await privacy_svc.update_request(db, request_id, ctx.org_id, payload)
    if not req:
        raise HTTPException(404, "Request not found")
    await audit_svc.write(
        db, organization_id=ctx.org_id, user_id=ctx.user_id,
        event_type="privacy.request.updated",
        message=f"Privacy request #{request_id} updated to {payload.get('status')}",
        severity=Severity.INFO,
    )
    await db.commit()
    return _req_out(req)


@router.post("/export")
async def export_data(
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    fmt = payload.get("format", "json")
    subject_ref = payload.get("subject_reference")
    data = await privacy_svc.export_trace_data(db, ctx.org_id, subject_ref, fmt)
    await audit_svc.write(
        db, organization_id=ctx.org_id, user_id=ctx.user_id,
        event_type="privacy.data.exported",
        message=f"Data export ({fmt}) for subject {subject_ref or 'all'}",
        severity=Severity.HIGH,
    )
    await db.commit()
    return {"format": fmt, "data": data, "subject_reference": subject_ref}


@router.post("/anonymize")
async def anonymize(
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    subject_ref = payload.get("subject_reference", "").strip()
    if not subject_ref:
        raise HTTPException(422, "subject_reference required")

    result = await privacy_svc.anonymize_subject(db, ctx.org_id, subject_ref)
    await audit_svc.write(
        db, organization_id=ctx.org_id, user_id=ctx.user_id,
        event_type="privacy.data.anonymized",
        message=f"Data anonymized for subject {result['anonymized_as']}",
        severity=Severity.HIGH,
        after_data={"traces_anonymized": result["traces_anonymized"]},
    )
    await db.commit()
    return result


@router.post("/run-retention")
async def run_retention(
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    result = await privacy_svc.run_retention(db, ctx.org_id)
    if "error" not in result:
        await audit_svc.write(
            db, organization_id=ctx.org_id, user_id=ctx.user_id,
            event_type="privacy.retention.executed",
            message="Retention policy executed",
            after_data=result, severity=Severity.MEDIUM,
        )
    await db.commit()
    return result


# ── Serialisers ───────────────────────────────────────────────────────────────

def _policy_out(p) -> dict:
    return {
        "id": p.id, "organization_id": p.organization_id,
        "traces_retention_days": p.traces_retention_days,
        "spans_retention_days": p.spans_retention_days,
        "audit_logs_retention_days": p.audit_logs_retention_days,
        "cost_records_retention_days": p.cost_records_retention_days,
        "anonymize_user_references": p.anonymize_user_references,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _req_out(r) -> dict:
    return {
        "id": r.id, "organization_id": r.organization_id,
        "requested_by_id": r.requested_by_id,
        "type": r.type, "status": r.status,
        "subject_reference": r.subject_reference,
        "notes": r.notes,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "created_at": r.created_at.isoformat(),
    }
