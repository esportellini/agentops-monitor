"""
Ingest-specific authentication: Bearer token = API key (not JWT).

The key is looked up by iterating active keys for the org prefix.
bcrypt verify confirms identity. This runs once per request; the key's
last_used_at is updated asynchronously via a Redis queue so the hot path
doesn't wait on an extra DB write.

Usage:
    ctx: IngestContext = Depends(api_key_auth)
    ctx: IngestContext = Depends(api_key_auth_for_project(project_id_path_param))
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.enums import ApiKeyStatus
from app.services.api_key import verify_api_key

log = get_logger(__name__)

_PREFIX = "agom_"


@dataclass
class IngestContext:
    api_key: ApiKey
    organization_id: int
    # project_id is None for org-scoped keys
    project_id: int | None


async def _resolve_key(raw_key: str, db: AsyncSession) -> ApiKey:
    """
    Find and verify the API key. Raises 401 on any failure.
    We fetch active keys that share the same prefix to minimise
    candidates before the expensive bcrypt verify.
    """
    if not raw_key.startswith(_PREFIX) or len(raw_key) < len(_PREFIX) + 8:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key format")

    prefix = f"{_PREFIX}{raw_key[len(_PREFIX):len(_PREFIX)+8]}"

    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_prefix == prefix,
            ApiKey.status == ApiKeyStatus.ACTIVE,
        )
    )
    candidates = list(result.scalars().all())

    if not candidates:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    for key in candidates:
        # Check expiry before the expensive bcrypt call
        if key.expires_at is not None:
            exp = key.expires_at.replace(tzinfo=timezone.utc) if key.expires_at.tzinfo is None else key.expires_at
            if datetime.now(timezone.utc) > exp:
                continue
        if verify_api_key(raw_key, key.key_hash):
            return key

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def _touch_key(api_key: ApiKey, db: AsyncSession) -> None:
    """Update last_used_at. Called after successful auth."""
    api_key.last_used_at = datetime.now(timezone.utc)
    # We rely on the outer request's commit to persist this.


async def api_key_auth(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> IngestContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

    raw_key = authorization.removeprefix("Bearer ").strip()
    api_key = await _resolve_key(raw_key, db)
    await _touch_key(api_key, db)

    return IngestContext(
        api_key=api_key,
        organization_id=api_key.organization_id,
        project_id=api_key.project_id,
    )
