"""Payment provider adapters.

A webhook body is never trusted on its own. Each adapter turns a delivery into a
`WebhookEvent` only after authenticating it:

* CloudPayments signs every notification with `Content-HMAC` (HMAC-SHA256 of the raw
  body with the API secret).
* YooKassa notifications are unsigned, so the adapter re-reads the payment from the
  YooKassa API with the shop credentials and uses that answer instead of the body.
* The stub provider exists for local development and tests and is refused in
  production by the API layer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode

import httpx

from app.core.config import settings
from app.services.billing.base import CheckoutResult, WebhookEvent

SUCCEEDED = "succeeded"
CANCELED = "canceled"
PENDING = "pending"
FAILED = "failed"


def _json_body(body: bytes) -> dict:
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("webhook body is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("webhook body must be a JSON object")
    return decoded


def _amount(value: object) -> float | None:
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None


def _yookassa_like_event(body: dict, payment: dict, provider: str) -> WebhookEvent:
    """Normalise a YooKassa-shaped payment object (also used by the stub)."""
    metadata = payment.get("metadata") or {}
    status = str(payment.get("status") or "unknown").lower()
    normalised = {
        "succeeded": SUCCEEDED,
        "canceled": CANCELED,
        "pending": PENDING,
        "waiting_for_capture": PENDING,
    }.get(status, FAILED if status == "failed" else PENDING)
    provider_payment_id = payment.get("id")
    event_type = str(body.get("event") or f"payment.{status}")
    # YooKassa notifications carry no delivery id; one payment legitimately produces
    # several events (waiting_for_capture → succeeded), so the event type is part of
    # the idempotency key.
    event_id = str(body.get("id") or f"{event_type}:{provider_payment_id}")
    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider_payment_id=str(provider_payment_id) if provider_payment_id else None,
        payment_id=str(metadata["payment_id"]) if metadata.get("payment_id") else None,
        user_id=str(metadata["user_id"]) if metadata.get("user_id") else None,
        tier=str(metadata["tier"]) if metadata.get("tier") else None,
        status=normalised,
        amount_rub=_amount((payment.get("amount") or {}).get("value")),
        raw_payload=body,
    )


class StubBillingProvider:
    name = "stub"

    async def create_checkout(
        self, *, payment_id: str, user_id: str, tier: str, amount_rub: float, idempotency_key: str
    ) -> CheckoutResult:
        query = urlencode({"payment_id": payment_id, "tier": tier, "amount": amount_rub})
        return CheckoutResult(
            provider=self.name,
            provider_payment_id=f"stub-{payment_id}",
            checkout_url=f"{settings.billing_return_url}?{query}",
            raw_payload={"stub": True, "payment_id": payment_id, "tier": tier},
        )

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        if settings.env == "production":
            raise ValueError("stub billing is disabled in production")
        payload = _json_body(body)
        return _yookassa_like_event(payload, payload.get("object") or payload, self.name)


class YooKassaProvider:
    name = "yookassa"
    base_url = "https://api.yookassa.ru/v3"

    def _auth(self) -> tuple[str, str]:
        if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
            raise RuntimeError("YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY are required")
        return settings.yookassa_shop_id, settings.yookassa_secret_key

    async def create_checkout(
        self, *, payment_id: str, user_id: str, tier: str, amount_rub: float, idempotency_key: str
    ) -> CheckoutResult:
        payload = {
            "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
            "capture": True,
            "description": f"Calmap {tier.upper()}: доступ на 30 дней",
            "confirmation": {"type": "redirect", "return_url": settings.billing_return_url},
            "metadata": {"payment_id": payment_id, "user_id": user_id, "tier": tier},
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.base_url}/payments",
                auth=self._auth(),
                headers={"Idempotence-Key": idempotency_key},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        confirmation = body.get("confirmation") or {}
        if not body.get("id") or not confirmation.get("confirmation_url"):
            raise RuntimeError("YooKassa response has no payment id or confirmation URL")
        return CheckoutResult(self.name, str(body["id"]), confirmation["confirmation_url"], body)

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        notification = _json_body(body)
        provider_payment_id = (notification.get("object") or {}).get("id")
        if not provider_payment_id:
            raise ValueError("YooKassa notification has no payment id")
        # The notification itself is unauthenticated: read the authoritative payment
        # state from the API instead of trusting the delivered body.
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/payments/{provider_payment_id}", auth=self._auth()
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("YooKassa API is unavailable") from exc
        if response.status_code == 404:
            raise ValueError("unknown YooKassa payment")
        if response.status_code >= 400:
            raise RuntimeError(f"YooKassa API returned {response.status_code}")
        payment = response.json()
        return _yookassa_like_event(
            {"event": notification.get("event"), "object": payment}, payment, self.name
        )


class CloudPaymentsProvider:
    name = "cloudpayments"

    async def create_checkout(
        self, *, payment_id: str, user_id: str, tier: str, amount_rub: float, idempotency_key: str
    ) -> CheckoutResult:
        if not settings.cloudpayments_checkout_url:
            raise RuntimeError("CLOUDPAYMENTS_CHECKOUT_URL is required")
        # The checkout URL is a merchant page with the CloudPayments widget. InvoiceId
        # and AccountId come back in the Pay notification and link it to this payment.
        query = urlencode(
            {
                "invoice_id": payment_id,
                "account_id": user_id,
                "tier": tier,
                "amount": f"{amount_rub:.2f}",
                "public_id": settings.cloudpayments_public_id,
            }
        )
        separator = "&" if "?" in settings.cloudpayments_checkout_url else "?"
        return CheckoutResult(
            self.name,
            f"cloudpayments-{payment_id}",
            f"{settings.cloudpayments_checkout_url}{separator}{query}",
            {"redirect": True},
        )

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        secret = settings.cloudpayments_secret
        if not secret:
            raise RuntimeError("CLOUDPAYMENTS_SECRET is required")
        signature = headers.get("content-hmac") or headers.get("x-content-hmac") or ""
        expected = base64.b64encode(
            hmac.new(secret.encode(), body, hashlib.sha256).digest()
        ).decode()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid CloudPayments webhook signature")

        # Notifications are form-encoded by default and JSON when configured so.
        if headers.get("content-type", "").startswith("application/json"):
            payload = _json_body(body)
        else:
            payload = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
        transaction_id = payload.get("TransactionId")
        status = str(payload.get("Status") or "").lower()
        normalised = {
            "completed": SUCCEEDED,
            "authorized": PENDING,
            "cancelled": CANCELED,
            "declined": FAILED,
        }.get(status, PENDING)
        data = payload.get("Data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data) if data else {}
            except json.JSONDecodeError:
                data = {}
        return WebhookEvent(
            event_id=f"{transaction_id}:{status}",
            event_type=f"cloudpayments.{status or 'unknown'}",
            provider_payment_id=str(transaction_id) if transaction_id else None,
            payment_id=str(payload["InvoiceId"]) if payload.get("InvoiceId") else None,
            user_id=str(payload["AccountId"]) if payload.get("AccountId") else None,
            tier=str(data.get("tier")) if isinstance(data, dict) and data.get("tier") else None,
            status=normalised,
            amount_rub=_amount(payload.get("Amount")),
            raw_payload=payload,
        )


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
