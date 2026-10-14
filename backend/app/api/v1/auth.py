from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select

from app.api.deps import CurrentAccess, CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import limit_auth
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.models import AccountDeletion, OAuthIdentity, PhoneCode, User
from app.services.oauth import OAuthVerificationError, verify_oauth_token
from app.services.consent import record_consent
from app.services.phone_auth import PhoneAuthError, check_code, issue_code, normalize_phone
from app.services.sms import SmsError
from app.services.subscription import new_subscription
from app.schemas.auth import (
    OAuthRequest,
    PhoneCodeOut,
    PhoneCodeRequest,
    PhoneVerifyRequest,
    ProfileUpdate,
    RefreshRequest,
    TokenPair,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)
rate_limited = [Depends(limit_auth)]

DESTROYED_CATEGORIES = [
    "учётные данные (номер телефона, коды входа)",
    "анкета (пол, возраст, рост, вес, цели, аллергии, тип питания, бюджет)",
    "нормы питания",
    "рационы",
    "дневник питания",
    "результаты распознавания фото",
    "тренировки",
    "прогресс веса и замеров",
    "сообщения AI-консультанту",
    "статус подписки и события оплаты",
    "привязка к Telegram",
    "журнал согласий",
]

# Sign-in only by methods 149-FZ permits: a Russian phone number (SMS code) or a
# Russian information system (VK ID). Google/Apple ID sign-in is fined under
# art. 13.55 of the Administrative Code since 7 July 2026.
SUPPORTED_PROVIDERS = {"vk"}

CONSENT_REQUIRED = "personal data consent is required"


def _tokens(user_id: uuid.UUID) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user_id), refresh_token=create_refresh_token(user_id)
    )


@router.post("/phone/code", response_model=PhoneCodeOut, dependencies=rate_limited)
async def send_phone_code(
    payload: PhoneCodeRequest, request: Request, session: DbSession
) -> PhoneCodeOut:
    """Send a sign-in code by SMS to a Russian mobile number."""
    phone = normalize_phone(payload.phone)
    if phone is None:
        raise HTTPException(422, "phone must be a Russian mobile number")
    ip = request.client.host if request.client else None
    try:
        issued = await issue_code(session, phone, ip)
    except PhoneAuthError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(exc.status, str(exc), headers=headers) from None
    except SmsError:
        logger.exception("SMS delivery failed")
        raise HTTPException(503, "sms delivery failed") from None
    # Commit before answering: the code must exist even if the client is fast.
    await session.commit()
    return PhoneCodeOut(expires_in=issued.expires_in, resend_in=issued.resend_in)


@router.post("/phone/verify", response_model=TokenPair, dependencies=rate_limited)
async def verify_phone_code(
    payload: PhoneVerifyRequest, request: Request, session: DbSession
) -> TokenPair:
    """Exchange the SMS code for tokens. The first sign-in creates the account and
    needs the separate personal-data consent; the code is not spent until then."""
    phone = normalize_phone(payload.phone)
    if phone is None:
        raise HTTPException(422, "phone must be a Russian mobile number")
    try:
        code_row = await check_code(session, phone, payload.code)
    except PhoneAuthError as exc:
        # Count the failed attempt even though the request fails.
        await session.commit()
        raise HTTPException(exc.status, str(exc)) from None

    user = await session.scalar(select(User).where(User.phone == phone))
    if user is None:
        if not payload.personal_data_consent:
            raise HTTPException(422, CONSENT_REQUIRED)
        user = User(phone=phone, region_code=settings.default_region_code)
        session.add(user)
        await session.flush()
        session.add(new_subscription(user.id))
        await record_consent(session, user.id, "personal_data", request)
    elif not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    code_row.consumed_at = datetime.now(timezone.utc)
    await session.flush()
    return _tokens(user.id)


@router.post("/oauth/{provider}", response_model=TokenPair, dependencies=rate_limited)
async def oauth(
    provider: str, payload: OAuthRequest, request: Request, session: DbSession
) -> TokenPair:
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
        if not payload.personal_data_consent:
            raise HTTPException(422, CONSENT_REQUIRED)
        user = User(email=email, region_code=settings.default_region_code)
        session.add(user)
        await session.flush()
        session.add(new_subscription(user.id))
        await record_consent(session, user.id, "personal_data", request)

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
        phone=user.phone,
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
        phone=user.phone,
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
    # Destruction record (Roskomnadzor order No. 179): the former account id and
    # what was destroyed, without contact data.
    session.add(
        AccountDeletion(
            user_ref=user.id,
            reason="user_request",
            method="удаление записей из базы данных",
            categories=DESTROYED_CATEGORIES,
        )
    )
    if user.phone:
        await session.execute(delete(PhoneCode).where(PhoneCode.phone == user.phone))
    # A Core delete lets Postgres cascade; the ORM would instead try to null out
    # the loaded relationships first.
    await session.execute(delete(User).where(User.id == user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
