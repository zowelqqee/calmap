"""Access rules derived from the stored payment status.

Everything the app may do is decided here, from `subscriptions` alone:

* paid and `paid_until` in the future → active, limits of the paid tier;
* never paid and the trial not over → trial;
* otherwise → no access, with the reason (trial ended, expired, revoked).
"""

from __future__ import annotations

import hashlib
import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    TIER_LIMITS,
    PaymentStatus,
    Subscription,
    SubscriptionEvent,
    TelegramLink,
    TelegramLinkCode,
    User,
)

AccessState = Literal["trial", "active", "trial_ended", "expired", "revoked"]

#: Text for the paywall and for 402 responses.
BLOCKED_MESSAGES: dict[str, str] = {
    "trial_ended": "Пробный период закончился. Оформите подписку, чтобы продолжить.",
    "expired": "Подписка закончилась. Продлите её, чтобы продолжить.",
    "revoked": "Подписка отменена. Оформите подписку, чтобы продолжить.",
}


@dataclass(frozen=True, slots=True)
class Access:
    state: AccessState
    tier: str | None  # trial | base | pro while access lasts, else the last paid tier
    paid_until: datetime | None
    trial_ends_at: datetime | None

    @property
    def has_access(self) -> bool:
        return self.state in ("trial", "active")

    @property
    def access_until(self) -> datetime | None:
        if self.state == "active":
            return self.paid_until
        if self.state == "trial":
            return self.trial_ends_at
        return None

    @property
    def limits(self) -> dict[str, int]:
        if not self.has_access or self.tier not in TIER_LIMITS:
            return {key: 0 for key in TIER_LIMITS["trial"]}
        return TIER_LIMITS[self.tier]

    def days_left(self, now: datetime | None = None) -> int | None:
        until = self.access_until
        if until is None:
            return None
        seconds = (until - (now or datetime.now(timezone.utc))).total_seconds()
        return max(0, math.ceil(seconds / 86400))


def evaluate(subscription: Subscription, now: datetime | None = None) -> Access:
    now = now or datetime.now(timezone.utc)
    status = subscription.payment_status
    if status == PaymentStatus.PAID and subscription.paid_until and subscription.paid_until > now:
        state: AccessState = "active"
        tier = subscription.tier
    elif status in (PaymentStatus.PAID, PaymentStatus.EXPIRED):
        state, tier = "expired", subscription.tier
    elif status == PaymentStatus.REVOKED:
        state, tier = "revoked", subscription.tier
    elif subscription.trial_ends_at and subscription.trial_ends_at > now:
        state, tier = "trial", "trial"
    else:
        state, tier = "trial_ended", None
    return Access(
        state=state,
        tier=tier,
        paid_until=subscription.paid_until,
        trial_ends_at=subscription.trial_ends_at,
    )


def new_subscription(user_id: uuid.UUID, starts_at: datetime | None = None) -> Subscription:
    """Row for a new account: trial from registration, nothing paid yet."""
    starts_at = starts_at or datetime.now(timezone.utc)
    return Subscription(
        user_id=user_id,
        payment_status=PaymentStatus.NONE,
        trial_ends_at=starts_at + timedelta(days=settings.trial_days),
    )


async def load_subscription(session: AsyncSession, user: User) -> Subscription:
    """The user's row, created on first read for accounts that predate it. A lapsed
    paid period is written back as `expired`, so the stored status stays truthful."""
    subscription = await session.scalar(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    if subscription is None:
        subscription = new_subscription(user.id, user.created_at)
        session.add(subscription)
        await session.flush()
    elif (
        subscription.payment_status == PaymentStatus.PAID
        and subscription.paid_until is not None
        and subscription.paid_until <= datetime.now(timezone.utc)
    ):
        subscription.payment_status = PaymentStatus.EXPIRED
        await session.flush()
    return subscription


# ----------------------------------------------------------------- Telegram linking


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def create_link_code(session: AsyncSession, user_id: uuid.UUID) -> tuple[str, datetime]:
    """Issue a one-time code for t.me/<bot>?start=<code>; older unused codes die."""
    now = datetime.now(timezone.utc)
    await session.execute(
        update(TelegramLinkCode)
        .where(TelegramLinkCode.user_id == user_id, TelegramLinkCode.used_at.is_(None))
        .values(used_at=now)
    )
    # Telegram allows 1-64 characters [A-Za-z0-9_-] in a start parameter.
    code = secrets.token_urlsafe(24)
    expires_at = now + timedelta(minutes=settings.telegram_link_code_ttl_minutes)
    session.add(TelegramLinkCode(user_id=user_id, code_hash=_hash_code(code), expires_at=expires_at))
    await session.flush()
    return code, expires_at


async def redeem_link_code(
    session: AsyncSession, code: str, telegram_user_id: int, telegram_username: str | None
) -> uuid.UUID | None:
    """Link the Telegram account to the code's owner. Returns the user id, or None
    for an unknown, used or expired code. A Telegram account pays for one app account
    at a time: linking it again moves the link."""
    now = datetime.now(timezone.utc)
    row = await session.scalar(
        select(TelegramLinkCode)
        .where(TelegramLinkCode.code_hash == _hash_code(code))
        .with_for_update()
    )
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    row.used_at = now

    for stale in (
        await session.scalars(
            select(TelegramLink).where(
                (TelegramLink.telegram_user_id == telegram_user_id)
                | (TelegramLink.user_id == row.user_id)
            )
        )
    ).all():
        await session.delete(stale)
    await session.flush()
    session.add(
        TelegramLink(
            user_id=row.user_id,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
        )
    )
    await session.flush()
    return row.user_id


async def user_for_telegram(session: AsyncSession, telegram_user_id: int) -> User | None:
    link = await session.scalar(
        select(TelegramLink).where(TelegramLink.telegram_user_id == telegram_user_id)
    )
    return await session.get(User, link.user_id) if link is not None else None


async def is_telegram_linked(session: AsyncSession, user_id: uuid.UUID) -> bool:
    return (
        await session.scalar(select(TelegramLink.id).where(TelegramLink.user_id == user_id))
        is not None
    )


# ------------------------------------------------------------------ status updates


async def apply_bot_event(
    session: AsyncSession,
    user: User,
    *,
    event_id: str,
    status: str,
    tier: str | None,
    paid_until: datetime | None,
    amount: float | None,
    currency: str | None,
    telegram_payment_charge_id: str | None,
    payload: dict,
) -> bool:
    """Record a status update from the bot. Returns False for a repeated event_id.

    The bot is the authority on payment status: the latest event sets it as given.
    """
    exists = await session.scalar(
        select(SubscriptionEvent.id).where(SubscriptionEvent.event_id == event_id)
    )
    if exists is not None:
        return False
    session.add(
        SubscriptionEvent(
            user_id=user.id,
            event_id=event_id,
            status=status,
            tier=tier,
            paid_until=paid_until,
            amount=amount,
            currency=currency,
            telegram_payment_charge_id=telegram_payment_charge_id,
            payload=payload,
        )
    )
    subscription = await load_subscription(session, user)
    if status == PaymentStatus.PAID:
        subscription.payment_status = PaymentStatus.PAID
        subscription.tier = tier
        subscription.paid_until = paid_until
    else:
        subscription.payment_status = PaymentStatus.REVOKED
        subscription.paid_until = min(
            subscription.paid_until or datetime.now(timezone.utc), datetime.now(timezone.utc)
        )
    subscription.last_event_id = event_id
    await session.flush()
    return True
