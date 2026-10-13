from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentSubscription, CurrentUser, DbSession
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import OAuthIdentity, Subscription, User
from app.services.oauth import OAuthVerificationError, verify_oauth_token
from app.schemas.auth import (
    LoginRequest,
    OAuthRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
    ProfileUpdate,
)

router = APIRouter(prefix="/auth", tags=["auth"])

SUPPORTED_PROVIDERS = {"apple", "google", "vk"}


def _tokens(user_id: uuid.UUID) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user_id), refresh_token=create_refresh_token(user_id)
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: DbSession) -> TokenPair:
    existing = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        region_code=settings.default_region_code,
    )
    session.add(user)
    await session.flush()
    session.add(Subscription(user_id=user.id, tier="free"))
    await session.flush()
    return _tokens(user.id)


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, session: DbSession) -> TokenPair:
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    # Same error for unknown email and wrong password: never leak which addresses exist.
    if user is None or not user.password_hash or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return _tokens(user.id)


@router.post("/oauth/{provider}", response_model=TokenPair)
async def oauth(provider: str, payload: OAuthRequest, session: DbSession) -> TokenPair:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported provider")

    try:
        subject, provider_email = await verify_oauth_token(provider, payload.id_token)
    except OAuthVerificationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    email = (payload.email or provider_email or "").lower() or None

    identity = await session.scalar(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == provider, OAuthIdentity.subject == subject
        )
    )
    if identity is not None:
        return _tokens(identity.user_id)

    user = None
    if email:
        user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, region_code=settings.default_region_code)
        session.add(user)
        await session.flush()
        session.add(Subscription(user_id=user.id, tier="free"))

    session.add(
        OAuthIdentity(user_id=user.id, provider=provider, subject=subject, email=email)
    )
    await session.flush()
    return _tokens(user.id)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: DbSession) -> TokenPair:
    try:
        subject = decode_token(payload.refresh_token, "refresh")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from None

    user = await session.get(User, uuid.UUID(subject))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return _tokens(user.id)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser, subscription: CurrentSubscription) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        region_code=user.region_code,
        onboarding_completed=user.onboarding_completed_at is not None,
        tier=subscription.tier,
    )


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: ProfileUpdate,
    user: CurrentUser,
    subscription: CurrentSubscription,
    session: DbSession,
) -> UserOut:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    await session.flush()
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        region_code=user.region_code,
        onboarding_completed=user.onboarding_completed_at is not None,
        tier=subscription.tier,
    )
