from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BillingEvent, Payment, Subscription, User
from app.db.models.billing import TIER_PRICES_RUB
from app.services.billing.providers import get_billing_provider


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


async def handle_webhook(session: AsyncSession, provider_name: str, body: bytes, headers: dict[str, str]) -> bool:
    provider = get_billing_provider(provider_name)
    event = provider.verify_webhook(body, headers)
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
    payment = None
    if event.payment_id:
        try:
            payment = await session.get(Payment, uuid.UUID(event.payment_id))
        except ValueError:
            payment = None
    if payment is None and event.provider_payment_id:
        payment = await session.scalar(
            select(Payment).where(Payment.provider_payment_id == event.provider_payment_id)
        )
    if payment is None:
        await session.flush()
        return True

    payment.raw_payload = event.raw_payload
    status = event.status.lower()
    if status in {"succeeded", "paid", "completed", "success"} or event.event_type in {"payment.succeeded", "payment_paid"}:
        payment.status = "paid"
        payment.paid_at = datetime.now(timezone.utc)
        subscription = await session.scalar(select(Subscription).where(Subscription.user_id == payment.user_id).limit(1))
        if subscription is None:
            subscription = Subscription(user_id=payment.user_id)
            session.add(subscription)
        subscription.tier = payment.tier
        subscription.status = "active"
        subscription.provider = provider_name
        subscription.provider_subscription_id = event.provider_payment_id or payment.provider_payment_id
        subscription.price_rub = payment.amount_rub
        subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
        subscription.auto_renew = True
    elif status in {"canceled", "cancelled", "expired"}:
        payment.status = "canceled"
    elif status in {"failed", "waiting_for_capture", "pending"}:
        payment.status = "pending" if status == "pending" else "failed"
    await session.flush()
    return True


async def cancel_subscription(session: AsyncSession, user: User) -> Subscription | None:
    subscription = await session.scalar(select(Subscription).where(Subscription.user_id == user.id).limit(1))
    if subscription is None:
        return None
    subscription.auto_renew = False
    await session.flush()
    return subscription
