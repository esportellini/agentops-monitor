from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import User


async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def record_login_success(db: AsyncSession, user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)


async def record_login_failure(db: AsyncSession, user: User, max_attempts: int, lockout_minutes: int) -> None:
    from datetime import timedelta

    user.failed_login_count += 1
    if user.failed_login_count >= max_attempts:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)


def is_locked(user: User) -> bool:
    if user.locked_until is None:
        return False
    return datetime.now(timezone.utc) < user.locked_until.replace(tzinfo=timezone.utc)
