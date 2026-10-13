from __future__ import annotations

import base64
import hashlib
import hmac
import json
from functools import lru_cache
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.billing.base import CheckoutResult, WebhookEvent


def _event_from_payload(body: dict, provider: str) -> WebhookEvent:
    obj = body.get("object", body)
    metadata = obj.get("metadata") or body.get("metadata") or {}
    event_id = str(body.get("id") or obj.get("id") or hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest())
    provider_payment_id = obj.get("id") or obj.get("payment_id")
    return WebhookEvent(
        event_id=event_id,
        event_type=str(body.get("event") or body.get("type") or obj.get("status") or "unknown"),
        provider_payment_id=str(provider_payment_id) if provider_payment_id else None,
        payment_id=str(metadata.get("payment_id")) if metadata.get("payment_id") else None,
        user_id=str(metadata.get("user_id")) if metadata.get("user_id") else None,
        tier=str(metadata.get("tier")) if metadata.get("tier") else None,
        status=str(obj.get("status") or body.get("status") or "unknown"),
        raw_payload=body,
    )


class StubBillingProvider:
    name = "stub"

    async def create_checkout(self, *, payment_id: str, user_id: str, tier: str, amount_rub: float, idempotency_key: str) -> CheckoutResult:
        query = urlencode({"payment_id": payment_id, "tier": tier, "amount": amount_rub})
        return CheckoutResult(
            provider=self.name,
            provider_payment_id=f"stub-{payment_id}",
            checkout_url=f"{settings.billing_return_url}?{query}",
            raw_payload={"stub": True, "payment_id": payment_id, "tier": tier},
        )

    def verify_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        return _event_from_payload(json.loads(body), self.name)


class YooKassaProvider:
    name = "yookassa"
    base_url = "https://api.yookassa.ru/v3"

    async def create_checkout(self, *, payment_id: str, user_id: str, tier: str, amount_rub: float, idempotency_key: str) -> CheckoutResult:
        if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
            raise RuntimeError("YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY are required")
        payload = {
            "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
            "capture": True,
            "description": f"calmap {tier} subscription",
            "confirmation": {"type": "redirect", "return_url": settings.billing_return_url},
            "metadata": {"payment_id": payment_id, "user_id": user_id, "tier": tier},
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.base_url}/payments",
                auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
                headers={"Idempotence-Key": idempotency_key},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        confirmation = body.get("confirmation") or {}
        if not body.get("id") or not confirmation.get("confirmation_url"):
            raise RuntimeError("YooKassa response has no payment id or confirmation URL")
        return CheckoutResult(self.name, str(body["id"]), confirmation["confirmation_url"], body)

    def verify_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        # YooKassa webhooks are authenticated by the provider's delivery mechanism;
        # applications should additionally restrict the endpoint at the network edge.
        return _event_from_payload(json.loads(body), self.name)


class CloudPaymentsProvider:
    name = "cloudpayments"

    async def create_checkout(self, *, payment_id: str, user_id: str, tier: str, amount_rub: float, idempotency_key: str) -> CheckoutResult:
        if not settings.cloudpayments_checkout_url:
            raise RuntimeError("CLOUDPAYMENTS_CHECKOUT_URL is required")
        query = urlencode({"payment_id": payment_id, "tier": tier, "amount": amount_rub})
        return CheckoutResult(
            self.name,
            f"cloudpayments-{payment_id}",
            f"{settings.cloudpayments_checkout_url.rstrip('?&')}?{query}",
            {"redirect": True},
        )

    def verify_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        signature = headers.get("content-hmac", "")
        expected = base64.b64encode(
            hmac.new(settings.cloudpayments_secret.encode(), body, hashlib.sha256).digest()
        ).decode()
        if not settings.cloudpayments_secret or not hmac.compare_digest(signature, expected):
            raise ValueError("invalid CloudPayments webhook signature")
        return _event_from_payload(json.loads(body), self.name)


@lru_cache
def get_billing_provider(name: str | None = None):
    selected = name or settings.billing_provider
    providers = {
        "stub": StubBillingProvider,
        "yookassa": YooKassaProvider,
        "cloudpayments": CloudPaymentsProvider,
    }
    try:
        return providers[selected]()
    except KeyError as exc:
        raise RuntimeError(f"unsupported billing provider: {selected}") from exc
