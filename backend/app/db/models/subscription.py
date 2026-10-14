"""Subscription status, as reported by the Telegram payment bot.

The bot is the only writer of payment status. The app never sells anything itself:
it reads the status below and opens the bot when the user has to pay.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey

#: Feature limits per access level. "trial" is the first days after registration.
#: Kept in code so a limit change ships with the code that enforces it.
TIER_LIMITS: dict[str, dict[str, int]] = {
    "trial": {"vision_per_day": 5, "plan_days": 7, "assistant_messages_per_month": 0},
    "base": {"vision_per_day": 5, "plan_days": 7, "assistant_messages_per_month": 0},
    "pro": {"vision_per_day": 30, "plan_days": 28, "assistant_messages_per_month": 200},
}
PAID_TIERS = ("base", "pro")


class PaymentStatus:
    NONE = "none"  # never paid
    PAID = "paid"  # paid until `paid_until`
    EXPIRED = "expired"  # the paid period ended
    REVOKED = "revoked"  # cancelled or refunded by the bot


class Subscription(Base, UUIDPrimaryKey, Timestamped):
    """One row per user: the current payment status."""

    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    #: Last paid tier (base | pro); NULL until the first payment.
    tier: Mapped[str | None] = mapped_column(String(16))
    payment_status: Mapped[str] = mapped_column(
        String(16), default=PaymentStatus.NONE, server_default=PaymentStatus.NONE, nullable=False
    )
    paid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Bot event that produced the current status.
    last_event_id: Mapped[str | None] = mapped_column(String(128))


class TelegramLink(Base, UUIDPrimaryKey, Timestamped):
    """Which Telegram account pays for which app account (one to one)."""

    __tablename__ = "telegram_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(String(64))


class TelegramLinkCode(Base, UUIDPrimaryKey, Timestamped):
    """One-time code the app puts into the bot's /start link.

    Only a SHA-256 hash is stored: a leaked table cannot be used to link accounts.
    """

    __tablename__ = "telegram_link_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubscriptionEvent(Base, UUIDPrimaryKey, Timestamped):
    """Ledger of status updates received from the bot (idempotent by event_id)."""

    __tablename__ = "subscription_events"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    tier: Mapped[str | None] = mapped_column(String(16))
    paid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
