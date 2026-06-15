"""
Audit logs API — filterable, exportable, immutable.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, require_org_member
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.enums import Severity

router = APIRouter(prefix="/organizations/{org_id}/audit-logs", tags=["audit"])


@router.get("")
async def list_audit_logs(
    event_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).where(AuditLog.organization_id == ctx.org_id)

    if event_type:
        q = q.where(AuditLog.event_type.ilike(f"%{event_type}%"))
    if severity:
        q = q.where(AuditLog.severity == Severity(severity))
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at <= until)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows = (await db.execute(q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))).scalars().all()

    return {"total": total, "items": [_log_out(r) for r in rows]}


@router.get("/export.csv", response_class=PlainTextResponse)
async def export_csv(
    event_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).where(AuditLog.organization_id == ctx.org_id)
    if event_type:
        q = q.where(AuditLog.event_type.ilike(f"%{event_type}%"))
    if severity:
        q = q.where(AuditLog.severity == Severity(severity))
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at <= until)

    rows = (await db.execute(q.order_by(AuditLog.created_at.desc()).limit(5000))).scalars().all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "event_type", "severity", "message", "entity_type", "entity_id", "user_id", "ip_address", "created_at"])
    for r in rows:
        w.writerow([r.id, r.event_type, r.severity, r.message, r.entity_type, r.entity_id, r.user_id, r.ip_address, r.created_at.isoformat()])

    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=audit-logs.csv"})


def _log_out(r: AuditLog) -> dict:
    return {
        "id": r.id,
        "event_type": r.event_type,
        "severity": r.severity,
        "message": r.message,
        "entity_type": r.entity_type,
        "entity_id": r.entity_id,
        "user_id": r.user_id,
        "ip_address": r.ip_address,
        "before_data": r.before_data,
        "after_data": r.after_data,
        "created_at": r.created_at.isoformat(),
    }
