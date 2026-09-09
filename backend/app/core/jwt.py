from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError as JWTError

from app.core.config import settings

_ALG = settings.jwt_algorithm
_SECRET = settings.jwt_secret


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=settings.jwt_access_expires_minutes),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


def create_refresh_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": _now(),
        "exp": _now() + timedelta(days=settings.jwt_refresh_expires_days),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


def decode_token(token: str, expected_type: str = "access") -> int:
    """Decode and validate a JWT. Returns user_id or raises JWTError."""
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALG])
    except JWTError:
        raise

    if payload.get("type") != expected_type:
        raise JWTError("wrong token type")

    sub = payload.get("sub")
    if not sub:
        raise JWTError("missing sub")

    return int(sub)
