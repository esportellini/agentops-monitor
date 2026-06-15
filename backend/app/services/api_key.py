"""
API key lifecycle: generate → hash → store prefix+hash, never the raw key.
The full key is shown to the user exactly once, at creation time.
"""
import secrets
from datetime import datetime, timezone

import bcrypt

from app.models.api_key import ApiKey
from app.models.audit import AuditLog
from app.models.enums import ApiKeyStatus, Severity

KEY_PREFIX_MARKER = "agom_"
KEY_BYTES = 32  # 256 bits → 64 hex chars


def generate_api_key() -> tuple[str, str, str]:
    """
    Returns (full_key, prefix, key_hash).
    full_key is shown once and never stored.
    prefix  is stored for user-facing identification.
    key_hash is stored for verification.
    """
    raw = secrets.token_hex(KEY_BYTES)
    full_key = f"{KEY_PREFIX_MARKER}{raw}"
    prefix = f"{KEY_PREFIX_MARKER}{raw[:8]}"
    key_hash = bcrypt.hashpw(full_key.encode(), bcrypt.gensalt()).decode()
    return full_key, prefix, key_hash


def verify_api_key(full_key: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(full_key.encode(), stored_hash.encode())
    except Exception:
        return False


async def create_api_key(
    db,
    *,
    organization_id: int,
    project_id: int | None,
    created_by_id: int,
    name: str,
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    full_key, prefix, key_hash = generate_api_key()

    api_key = ApiKey(
        organization_id=organization_id,
        project_id=project_id,
        created_by_id=created_by_id,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        status=ApiKeyStatus.ACTIVE,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.flush()

    return api_key, full_key


async def revoke_api_key(
    db,
    *,
    api_key: ApiKey,
    revoked_by_id: int,
    organization_id: int,
) -> None:
    now = datetime.now(timezone.utc)
    api_key.status = ApiKeyStatus.REVOKED
    api_key.revoked_by_id = revoked_by_id
    api_key.revoked_at = now

    audit = AuditLog(
        organization_id=organization_id,
        user_id=revoked_by_id,
        event_type="api_key.revoked",
        entity_type="api_key",
        entity_id=str(api_key.id),
        severity=Severity.MEDIUM,
        message=f"API key '{api_key.name}' ({api_key.key_prefix}…) revoked",
        created_at=now,
    )
    db.add(audit)
