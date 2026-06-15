from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.enums import Severity


async def write(
    db: AsyncSession,
    *,
    organization_id: int,
    event_type: str,
    message: str,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    severity: Severity = Severity.INFO,
    before_data: dict | None = None,
    after_data: dict | None = None,
    ip_address: str | None = None,
) -> None:
    entry = AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        severity=severity,
        message=message,
        before_data=before_data,
        after_data=after_data,
        ip_address=ip_address,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
