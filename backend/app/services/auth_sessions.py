"""Sign-in sessions: issuing, rotating and revoking token pairs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import TokenClaims, create_access_token, create_refresh_token, new_jti
from app.db.models import AuthSession
from app.schemas.auth import TokenPair

#: A refresh token replaced this recently is still accepted once more: the client may
#: have lost the answer that carried its successor.
ROTATION_GRACE = timedelta(minutes=2)


class SessionRejected(Exception):
    """The refresh token is expired, revoked, or was used after rotation."""


def _pair(auth: AuthSession) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(auth.user_id, auth.id),
        refresh_token=create_refresh_token(auth.user_id, auth.id, auth.refresh_jti),
    )


async def start_session(session: AsyncSession, user_id: uuid.UUID) -> TokenPair:
    now = datetime.now(timezone.utc)
    auth = AuthSession(
        id=uuid.uuid4(),
        user_id=user_id,
        refresh_jti=new_jti(),
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
    )
    session.add(auth)
    await session.flush()
    return _pair(auth)


async def rotate(session: AsyncSession, claims: TokenClaims) -> TokenPair:
    now = datetime.now(timezone.utc)
    auth = await session.scalar(
        select(AuthSession).where(AuthSession.id == claims.session_id).with_for_update()
    )
    if (
        auth is None
        or auth.user_id != claims.user_id
        or auth.revoked_at is not None
        or auth.expires_at <= now
    ):
        raise SessionRejected
    in_grace = (
        claims.jti == auth.previous_jti
        and auth.rotated_at is not None
        and now - auth.rotated_at < ROTATION_GRACE
    )
    if claims.jti != auth.refresh_jti and not in_grace:
        # A replaced token came back: someone holds a copy. End the session for
        # both the thief and the owner; the owner signs in again by SMS.
        auth.revoked_at = now
        await session.commit()
        raise SessionRejected
    auth.previous_jti = auth.refresh_jti if claims.jti == auth.refresh_jti else auth.previous_jti
    auth.refresh_jti = new_jti()
    auth.rotated_at = now
    await session.flush()
    return _pair(auth)


async def is_active(session: AsyncSession, claims: TokenClaims) -> bool:
    auth = await session.get(AuthSession, claims.session_id)
    return (
        auth is not None
        and auth.user_id == claims.user_id
        and auth.revoked_at is None
        and auth.expires_at > datetime.now(timezone.utc)
    )


async def started_recently(session: AsyncSession, claims: TokenClaims, minutes: int) -> bool:
    """Whether the session behind these claims was signed in within `minutes`."""
    auth = await session.get(AuthSession, claims.session_id)
    return auth is not None and datetime.now(timezone.utc) - auth.created_at < timedelta(
        minutes=minutes
    )


async def revoke(session: AsyncSession, session_id: uuid.UUID) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def revoke_all(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
