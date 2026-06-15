from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.enums import ApiKeyStatus


async def get_by_id(db: AsyncSession, key_id: int, org_id: int) -> ApiKey | None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == org_id)
    )
    return result.scalar_one_or_none()


async def list_for_org(db: AsyncSession, org_id: int) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.organization_id == org_id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())
