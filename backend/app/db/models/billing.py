from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey

#: Feature limits per tier. Kept in code (not the DB) so a limit change ships with the
#: code that enforces it; the values are what protects the unit economics of the
#: vision feature.
TIER_LIMITS: dict[str, dict[str, int]] = {
    "free": {"vision_per_day": 1, "plan_days": 1, "assistant_messages_per_month": 0},
    "base": {"vision_per_day": 5, "plan_days": 7, "assistant_messages_per_month": 0},
    "pro": {"vision_per_day": 30, "plan_days": 28, "assistant_messages_per_month": 200},
}

TIER_PRICES_RUB: dict[str, int] = {"base": 299, "pro": 499}


class Subscription(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tier: Mapped[str] = mapped_column(String(16), default="free", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    #: yookassa | cloudpayments | rustore | manual — Apple/Google IAP are unavailable
    #: for RU cards, so entitlements are granted by our own billing, never by the store.
    provider: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(128), index=True)
    price_rub: Mapped[float | None] = mapped_column(Float)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    @property
    def limits(self) -> dict[str, int]:
        return TIER_LIMITS.get(self.tier, TIER_LIMITS["free"])


class Payment(Base, UUIDPrimaryKey, Timestamped):
    """One checkout attempt.

    A payment is deliberately separate from `Subscription`: providers can retry a
    webhook, a user can abandon a checkout, and a second purchase can happen after a
    previous period expires. The provider id and idempotency key make all of those
    cases safe to reconcile.
    """

    __tablename__ = "payments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_rub: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), index=True)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class BillingEvent(Base, UUIDPrimaryKey, Timestamped):
    """Idempotency ledger for provider webhooks."""

    __tablename__ = "billing_events"

    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (UniqueConstraint("provider", "event_id", name="provider_event"),)
