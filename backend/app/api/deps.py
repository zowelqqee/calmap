from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.models import Subscription, User, UserProfile
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        subject = decode_token(credentials.credentials, "access")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from None

    user = await session.get(User, uuid.UUID(subject))
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
    """Every user has an entitlement row; free tier is created lazily on first read."""
    subscription = await session.scalar(
        select(Subscription).where(Subscription.user_id == user.id).limit(1)
    )
    if subscription is None:
        subscription = Subscription(user_id=user.id, tier="free")
        session.add(subscription)
        await session.flush()
    elif (
        subscription.current_period_end is not None
        and subscription.current_period_end <= datetime.now(timezone.utc)
        and subscription.status == "active"
    ):
        subscription.status = "expired"
        await session.flush()
    return subscription


CurrentSubscription = Annotated[Subscription, Depends(get_subscription)]


async def require_nutrition_access(
    subscription: CurrentSubscription,
) -> Subscription:
    now = datetime.now(timezone.utc)
    expired = (
        subscription.current_period_end is not None
        and subscription.current_period_end <= now
    )
    if subscription.status != "active" or expired:
        subscription.status = "expired"
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "subscription expired: renew access to nutrition plans",
        )
    return subscription


NutritionSubscription = Annotated[Subscription, Depends(require_nutrition_access)]
