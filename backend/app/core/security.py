from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt

from app.core.config import settings

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    jti: str


def _create_token(
    user_id: uuid.UUID, session_id: uuid.UUID, token_type: TokenType, ttl: timedelta, jti: str
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": jti,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def new_jti() -> str:
    return uuid.uuid4().hex


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    return _create_token(
        user_id,
        session_id,
        "access",
        timedelta(minutes=settings.access_token_ttl_minutes),
        new_jti(),
    )


def create_refresh_token(user_id: uuid.UUID, session_id: uuid.UUID, jti: str) -> str:
    return _create_token(
        user_id, session_id, "refresh", timedelta(days=settings.refresh_token_ttl_days), jti
    )


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    """Return the claims or raise jwt exceptions (ValueError for malformed ids)."""
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub", "sid", "typ", "jti"]},
    )
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return TokenClaims(
        user_id=uuid.UUID(str(payload["sub"])),
        session_id=uuid.UUID(str(payload["sid"])),
        jti=str(payload["jti"]),
    )
