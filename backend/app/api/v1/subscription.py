"""Subscription status for the app and one-time links to the payment bot."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSubscription, CurrentUser, DbSession
from app.core.config import settings
from app.db.models import Subscription
from app.schemas.subscription import SubscriptionOut, TelegramLinkOut
from app.services.subscription import (
    BLOCKED_MESSAGES,
    create_link_code,
    evaluate,
    is_telegram_linked,
)

router = APIRouter(prefix="/me/subscription", tags=["subscription"])


async def subscription_out(session: AsyncSession, subscription: Subscription) -> SubscriptionOut:
    access = evaluate(subscription)
    return SubscriptionOut(
        state=access.state,
        has_access=access.has_access,
        tier=access.tier,
        payment_status=subscription.payment_status,
        paid_until=subscription.paid_until,
        trial_ends_at=subscription.trial_ends_at,
        access_until=access.access_until,
        days_left=access.days_left(),
        limits=access.limits,
        message=BLOCKED_MESSAGES.get(access.state),
        telegram_linked=await is_telegram_linked(session, subscription.user_id),
        payment_available=bool(settings.telegram_bot_username),
    )


@router.get("", response_model=SubscriptionOut)
async def get_subscription(
    subscription: CurrentSubscription, session: DbSession
) -> SubscriptionOut:
    """The only source the app uses to decide what is available."""
    return await subscription_out(session, subscription)


@router.post(
    "/telegram-link", response_model=TelegramLinkOut, status_code=status.HTTP_201_CREATED
)
async def telegram_link(user: CurrentUser, session: DbSession) -> TelegramLinkOut:
    """A one-time t.me link that opens the payment bot already tied to this account."""
    if not settings.telegram_bot_username:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "оплата временно недоступна")
    code, expires_at = await create_link_code(session, user.id)
    username = settings.telegram_bot_username.lstrip("@")
    return TelegramLinkOut(url=f"https://t.me/{username}?start={code}", expires_at=expires_at)
