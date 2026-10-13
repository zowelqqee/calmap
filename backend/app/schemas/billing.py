from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BillingPlanOut(BaseModel):
    tier: str
    price_rub: int
    period_days: int = 30
    limits: dict[str, int]


class CheckoutRequest(BaseModel):
    tier: str = Field(pattern="^(base|pro)$")


class CheckoutOut(BaseModel):
    payment_id: uuid.UUID
    tier: str
    amount_rub: float
    currency: str
    status: str
    provider: str
    checkout_url: str


class SubscriptionOut(BaseModel):
    tier: str
    status: str
    provider: str
    price_rub: float | None
    current_period_end: datetime | None
    auto_renew: bool
    limits: dict[str, int]
