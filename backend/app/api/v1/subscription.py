"""Subscription status — the only thing the app reads to decide access."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSubscription, DbSession
from app.db.models import Subscription
from app.schemas.subscription import SubscriptionOut
from app.services.subscription import (
    BLOCKED_MESSAGES,
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
    )


@router.get("", response_model=SubscriptionOut)
async def get_subscription(
    subscription: CurrentSubscription, session: DbSession
) -> SubscriptionOut:
    """The only source the app uses to decide what is available."""
    return await subscription_out(session, subscription)
