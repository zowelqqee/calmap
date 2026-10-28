from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SubscriptionOut(BaseModel):
    #: trial | active | trial_ended | expired | revoked
    state: str
    has_access: bool
    #: trial | base | pro while access lasts; the last paid tier otherwise
    tier: str | None
    payment_status: str
    paid_until: datetime | None
    trial_ends_at: datetime | None
    access_until: datetime | None
    days_left: int | None
    limits: dict[str, int]
    #: Russian text for the paywall when there is no access
    message: str | None
    telegram_linked: bool


# ------------------------------------------------------------------ bot contract


class BotLinkRequest(BaseModel):
    """Sent after the user shares their contact in the bot. The bot must check that
    the shared contact belongs to the sender (contact.user_id == from.id)."""

    phone: str = Field(min_length=10, max_length=20)
    telegram_user_id: int = Field(gt=0)
    telegram_username: str | None = Field(default=None, max_length=64)


class BotLoginCodeRequest(BaseModel):
    """The user asked the bot for a sign-in code and shared their own contact (the
    bot checks contact.user_id == from.id)."""

    phone: str = Field(min_length=10, max_length=20)
    telegram_user_id: int = Field(gt=0)


class BotLoginCodeOut(BaseModel):
    code: str
    expires_in: int
    #: False: signing in with this code creates the account.
    account_exists: bool


class BotLinkOut(BaseModel):
    user_id: uuid.UUID
    subscription: SubscriptionOut


class BotSubscriptionEvent(BaseModel):
    """A payment status change, pushed by the Telegram bot."""

    #: Unique per event; repeats are ignored (safe retries).
    event_id: str = Field(min_length=1, max_length=128)
    telegram_user_id: int = Field(gt=0)
    #: Calmap account the payment was made for (from /v1/bot/link). When given, the
    #: event is refused if the Telegram account has since been linked elsewhere, so
    #: a payment or refund can never land on another account.
    user_id: uuid.UUID | None = None
    #: paid — access until `paid_until`; revoked — refund/cancellation, access ends now
    status: Literal["paid", "revoked"]
    tier: Literal["base", "pro"] | None = None
    paid_until: datetime | None = None
    amount: float | None = Field(default=None, ge=0)
    #: RUB, or XTR for Telegram Stars
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    telegram_payment_charge_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def paid_needs_tier_and_period(self) -> BotSubscriptionEvent:
        if self.status == "paid":
            if self.tier is None or self.paid_until is None:
                raise ValueError("a paid event needs tier and paid_until")
            if self.paid_until.tzinfo is None:
                raise ValueError("paid_until must include a timezone offset")
            now = datetime.now(timezone.utc)
            if not now < self.paid_until <= now + timedelta(days=400):
                raise ValueError("paid_until must be in the future and within 400 days")
        return self


class BotEventOut(BaseModel):
    processed: bool
    subscription: SubscriptionOut


class ExpiringOut(BaseModel):
    telegram_user_id: int
    state: str
    tier: str | None
    access_until: datetime
