from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BillingEvent, Payment, Subscription, User
from app.db.models.billing import TIER_PRICES_RUB
from app.services.billing.providers import get_billing_provider

logger = logging.getLogger(__name__)


async def create_checkout(session: AsyncSession, user: User, tier: str) -> Payment:
    if tier not in TIER_PRICES_RUB:
        raise ValueError("tier must be base or pro")
    payment = Payment(
        user_id=user.id,
        tier=tier,
        amount_rub=TIER_PRICES_RUB[tier],
        provider=get_billing_provider().name,
        idempotency_key=uuid.uuid4().hex,
    )
    session.add(payment)
    await session.flush()
    try:
        result = await get_billing_provider().create_checkout(
            payment_id=str(payment.id),
            user_id=str(user.id),
            tier=tier,
            amount_rub=payment.amount_rub,
            idempotency_key=payment.idempotency_key,
        )
    except (httpx.HTTPError, OSError) as exc:
        payment.status = "failed"
        await session.flush()
        raise RuntimeError("billing provider is unavailable") from exc
    payment.provider = result.provider
    payment.provider_payment_id = result.provider_payment_id
    payment.checkout_url = result.checkout_url
    payment.raw_payload = result.raw_payload
    await session.flush()
    return payment


PERIOD = timedelta(days=30)


async def handle_webhook(
    session: AsyncSession, provider_name: str, body: bytes, headers: dict[str, str]
) -> bool:
    """Apply an authenticated provider event exactly once.

    Returns False for a duplicate delivery. Events that do not match a known payment
    of the same provider and amount are recorded in the ledger but grant nothing.
    """
    provider = get_billing_provider(provider_name)
    event = await provider.verify_webhook(body, headers)
    exists = await session.scalar(
        select(BillingEvent).where(
            BillingEvent.provider == provider_name,
            BillingEvent.event_id == event.event_id,
        )
    )
    if exists is not None:
        return False
    session.add(BillingEvent(
        provider=provider_name,
        event_id=event.event_id,
        event_type=event.event_type,
        payload=event.raw_payload,
    ))

    payment = await _find_payment(session, event)
    if payment is None or payment.provider != provider_name:
        logger.warning(
            "billing event %s from %s matches no payment", event.event_id, provider_name
        )
        await session.flush()
        return True
    if event.amount_rub is not None and abs(event.amount_rub - payment.amount_rub) > 0.009:
        logger.warning(
            "billing event %s amount %.2f does not match payment %s amount %.2f",
            event.event_id, event.amount_rub, payment.id, payment.amount_rub,
        )
        await session.flush()
        return True

    payment.raw_payload = event.raw_payload
    if event.provider_payment_id and provider_name != "cloudpayments":
        payment.provider_payment_id = event.provider_payment_id
    if event.status == "succeeded":
        if payment.status != "paid":
            payment.status = "paid"
            payment.paid_at = datetime.now(timezone.utc)
            await _grant(session, payment, provider_name, event.provider_payment_id)
    elif payment.status != "paid":
        payment.status = event.status
    await session.flush()
    return True


async def _find_payment(session: AsyncSession, event) -> Payment | None:
    if event.payment_id:
        try:
            payment = await session.get(Payment, uuid.UUID(event.payment_id))
        except ValueError:
            payment = None
        if payment is not None:
            return payment
    if event.provider_payment_id:
        return await session.scalar(
            select(Payment).where(Payment.provider_payment_id == event.provider_payment_id)
        )
    return None


async def _grant(
    session: AsyncSession, payment: Payment, provider_name: str, provider_payment_id: str | None
) -> None:
    """Extend access by one period. Paying again before expiry adds to the remaining
    time instead of discarding it."""
    now = datetime.now(timezone.utc)
    subscription = await session.scalar(
        select(Subscription).where(Subscription.user_id == payment.user_id).limit(1)
    )
    if subscription is None:
        subscription = Subscription(user_id=payment.user_id)
        session.add(subscription)
    starts_at = now
    if (
        subscription.tier == payment.tier
        and subscription.status == "active"
        and subscription.current_period_end is not None
        and subscription.current_period_end > now
    ):
        starts_at = subscription.current_period_end
    subscription.tier = payment.tier
    subscription.status = "active"
    subscription.provider = provider_name
    subscription.provider_subscription_id = provider_payment_id or payment.provider_payment_id
    subscription.price_rub = payment.amount_rub
    subscription.current_period_end = starts_at + PERIOD
    # Purchases are one-off 30-day passes: nothing is charged automatically.
    subscription.auto_renew = False


def expire_paid_tier(subscription: Subscription) -> bool:
    """Downgrade a lapsed paid pass back to the free tier. Returns True if changed."""
    if (
        subscription.tier != "free"
        and subscription.current_period_end is not None
        and subscription.current_period_end <= datetime.now(timezone.utc)
    ):
        subscription.tier = "free"
        subscription.status = "active"
        subscription.current_period_end = None
        subscription.auto_renew = False
        return True
    return False


async def cancel_subscription(session: AsyncSession, user: User) -> Subscription | None:
    subscription = await session.scalar(select(Subscription).where(Subscription.user_id == user.id).limit(1))
    if subscription is None:
        return None
    subscription.auto_renew = False
    await session.flush()
    return subscription
