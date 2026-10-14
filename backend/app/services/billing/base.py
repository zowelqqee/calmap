from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    provider: str
    provider_payment_id: str
    checkout_url: str
    raw_payload: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    event_id: str
    event_type: str
    provider_payment_id: str | None
    payment_id: str | None
    user_id: str | None
    tier: str | None
    #: One of succeeded | pending | canceled | failed, already normalised.
    status: str
    amount_rub: float | None
    raw_payload: dict


class BillingProvider(Protocol):
    name: str

    async def create_checkout(
        self,
        *,
        payment_id: str,
        user_id: str,
        tier: str,
        amount_rub: float,
        idempotency_key: str,
    ) -> CheckoutResult: ...

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent: ...

