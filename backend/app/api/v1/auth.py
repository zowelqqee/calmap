from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select

from app.api.deps import CurrentAccess, CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import limit_auth
from app.core.security import (
    create_access_token,
    create_refresh_token,
    DUMMY_PASSWORD_HASH,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import OAuthIdentity, User
from app.services.oauth import OAuthVerificationError, verify_oauth_token
from app.services.subscription import new_subscription
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
rate_limited = [Depends(limit_auth)]

SUPPORTED_PROVIDERS = {"apple", "google", "vk"}


def _tokens(user_id: uuid.UUID) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user_id), refresh_token=create_refresh_token(user_id)
    )


@router.post(
    "/register",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    dependencies=rate_limited,
)
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
    session.add(new_subscription(user.id))
    await session.flush()
    return _tokens(user.id)


@router.post("/login", response_model=TokenPair, dependencies=rate_limited)
async def login(payload: LoginRequest, session: DbSession) -> TokenPair:
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    # Same error and the same bcrypt cost for an unknown email and a wrong password:
    # never leak which addresses exist.
    password_hash = user.password_hash if user is not None and user.password_hash else None
    valid = verify_password(payload.password, password_hash or DUMMY_PASSWORD_HASH)
    if password_hash is None or not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return _tokens(user.id)


@router.post("/oauth/{provider}", response_model=TokenPair, dependencies=rate_limited)
async def oauth(provider: str, payload: OAuthRequest, session: DbSession) -> TokenPair:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported provider")

    try:
        subject, provider_email = await verify_oauth_token(provider, payload.id_token)
    except OAuthVerificationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    # Only a provider-verified address may link to an existing account. The optional
    # client-supplied `email` is ignored: trusting it would let anyone with a valid
    # token for their own account sign in to someone else's.
    email = (provider_email or "").lower() or None

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
        session.add(new_subscription(user.id))

    session.add(
        OAuthIdentity(user_id=user.id, provider=provider, subject=subject, email=email)
    )
    await session.flush()
    return _tokens(user.id)


@router.post("/refresh", response_model=TokenPair, dependencies=rate_limited)
async def refresh(payload: RefreshRequest, session: DbSession) -> TokenPair:
    try:
        user_id = uuid.UUID(decode_token(payload.refresh_token, "refresh"))
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from None

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return _tokens(user.id)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser, access: CurrentAccess) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        region_code=user.region_code,
        onboarding_completed=user.onboarding_completed_at is not None,
        tier=access.tier if access.has_access else None,
    )


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: ProfileUpdate,
    user: CurrentUser,
    access: CurrentAccess,
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
        tier=access.tier if access.has_access else None,
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(user: CurrentUser, session: DbSession) -> Response:
    """Permanently delete the account and every record that belongs to it.

    Required by the App Store and Google Play and by 152-FZ (withdrawal of consent).
    All user-owned tables reference `users.id` with ON DELETE CASCADE, so one delete
    removes the profile, diary, plans, progress, recognitions, chats and payments.
    Outstanding tokens stop working because their subject no longer exists.
    """
    # A Core delete lets Postgres cascade; the ORM would instead try to null out
    # the loaded relationships first.
    await session.execute(delete(User).where(User.id == user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
