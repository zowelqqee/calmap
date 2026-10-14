from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenClaims, decode_token
from app.services.auth_sessions import is_active as session_is_active
from app.db.models import Subscription, User, UserProfile
from app.db.session import get_db
from app.services.subscription import (
    BLOCKED_MESSAGES,
    Access,
    evaluate,
    load_subscription,
)

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_token_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
) -> TokenClaims:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        claims = decode_token(credentials.credentials, "access")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired") from None
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from None
    # A signed-out or revoked session stops working at once, not when the token expires.
    if not await session_is_active(session, claims):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session ended")
    return claims


CurrentClaims = Annotated[TokenClaims, Depends(get_token_claims)]


async def get_current_user(claims: CurrentClaims, session: DbSession) -> User:
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_profile(user: CurrentUser, session: DbSession) -> UserProfile:
    profile = await session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "onboarding is not complete: no profile yet"
        )
    return profile


CurrentProfile = Annotated[UserProfile, Depends(get_current_profile)]


async def get_subscription(user: CurrentUser, session: DbSession) -> Subscription:
    return await load_subscription(session, user)


CurrentSubscription = Annotated[Subscription, Depends(get_subscription)]


async def get_access(subscription: CurrentSubscription) -> Access:
    return evaluate(subscription)


CurrentAccess = Annotated[Access, Depends(get_access)]


async def require_access(access: CurrentAccess) -> Access:
    """Gate for every feature: only a paid period or the trial passes."""
    if not access.has_access:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {
                "code": "subscription_required",
                "state": access.state,
                "message": BLOCKED_MESSAGES[access.state],
            },
        )
    return access


ActiveAccess = Annotated[Access, Depends(require_access)]
