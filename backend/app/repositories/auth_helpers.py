from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import OrganizationMember


async def first_org_id_for_user(db: AsyncSession, user_id: int) -> int | None:
    result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user_id)
        .limit(1)
    )
    return result.scalar_one_or_none()
