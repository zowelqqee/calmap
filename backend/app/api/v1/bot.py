"""Server-to-server API for the Telegram payment bot.

The bot authenticates with the shared secret in `X-Bot-Secret`. It links a Telegram
account to the app account with the same phone number (shared via Telegram's
contact button), then pushes every payment status change here. These endpoints are the only way payment
status enters the database.
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.v1.subscription import subscription_out
from app.core.config import settings
from app.db.models import PaymentStatus, Subscription, TelegramLink
from app.schemas.subscription import (
    BotEventOut,
    BotLinkOut,
    BotLinkRequest,
    BotSubscriptionEvent,
    ExpiringOut,
    SubscriptionOut,
)
from app.services.subscription import (
    apply_bot_event,
    evaluate,
    link_telegram_by_phone,
    load_subscription,
    user_for_telegram,
)
from app.services.phone_auth import normalize_phone

logger = logging.getLogger(__name__)


async def verify_bot(x_bot_secret: Annotated[str | None, Header()] = None) -> None:
    secret = settings.telegram_bot_api_secret
    if not secret:
        # Not configured: behave as if the API did not exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    if x_bot_secret is None or not hmac.compare_digest(x_bot_secret, secret):
        logger.warning("bot API call with an invalid secret")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bot secret")


router = APIRouter(prefix="/bot", tags=["telegram bot"], dependencies=[Depends(verify_bot)])


@router.post("/link", response_model=BotLinkOut)
async def link(payload: BotLinkRequest, session: DbSession) -> BotLinkOut:
    """Tie the Telegram account to the app account with the same phone number."""
    phone = normalize_phone(payload.phone)
    if phone is None:
        raise HTTPException(422, "phone must be a Russian mobile number")
    user = await link_telegram_by_phone(
        session, phone, payload.telegram_user_id, payload.telegram_username
    )
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no account with this phone")
    subscription = await load_subscription(session, user)
    return BotLinkOut(user_id=user.id, subscription=await subscription_out(session, subscription))


@router.post("/subscription/events", response_model=BotEventOut)
async def subscription_event(payload: BotSubscriptionEvent, session: DbSession) -> BotEventOut:
    """Payment confirmed (`paid`) or refunded/cancelled (`revoked`)."""
    user = await user_for_telegram(session, payload.telegram_user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "telegram account is not linked")
    processed = await apply_bot_event(
        session,
        user,
        event_id=payload.event_id,
        status=payload.status,
        tier=payload.tier,
        paid_until=payload.paid_until,
        amount=payload.amount,
        currency=payload.currency.upper() if payload.currency else None,
        telegram_payment_charge_id=payload.telegram_payment_charge_id,
        payload=payload.model_dump(mode="json"),
    )
    subscription = await load_subscription(session, user)
    return BotEventOut(
        processed=processed, subscription=await subscription_out(session, subscription)
    )


@router.get("/subscription/{telegram_user_id}", response_model=SubscriptionOut)
async def subscription_status(telegram_user_id: int, session: DbSession) -> SubscriptionOut:
    user = await user_for_telegram(session, telegram_user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "telegram account is not linked")
    return await subscription_out(session, await load_subscription(session, user))


@router.get("/subscriptions/expiring", response_model=list[ExpiringOut])
async def expiring(
    session: DbSession,
    within_hours: int = Query(default=24, ge=1, le=24 * 14),
) -> list[ExpiringOut]:
    """Linked users whose access ends within the window — for bot reminders."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=within_hours)
    rows = (
        await session.execute(
            select(Subscription, TelegramLink.telegram_user_id)
            .join(TelegramLink, TelegramLink.user_id == Subscription.user_id)
            .where(
                (
                    (Subscription.payment_status == PaymentStatus.PAID)
                    & (Subscription.paid_until > now)
                    & (Subscription.paid_until <= horizon)
                )
                | (
                    (Subscription.payment_status == PaymentStatus.NONE)
                    & (Subscription.trial_ends_at > now)
                    & (Subscription.trial_ends_at <= horizon)
                )
            )
        )
    ).all()
    out = []
    for subscription, telegram_user_id in rows:
        access = evaluate(subscription, now)
        if access.access_until is not None:
            out.append(
                ExpiringOut(
                    telegram_user_id=telegram_user_id,
                    state=access.state,
                    tier=access.tier,
                    access_until=access.access_until,
                )
            )
    return out
