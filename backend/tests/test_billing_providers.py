"""Webhook authentication of the real payment adapters (no network)."""

from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import urlencode

import httpx
import pytest

from app.core.config import settings
from app.services.billing.providers import CloudPaymentsProvider, YooKassaProvider


async def test_cloudpayments_rejects_unsigned_and_accepts_signed_form(monkeypatch):
    monkeypatch.setattr(settings, "cloudpayments_secret", "cp-secret")
    body = urlencode(
        {"TransactionId": "777", "Amount": "499.00", "Status": "Completed",
         "InvoiceId": "pay-1", "AccountId": "user-1"}
    ).encode()
    provider = CloudPaymentsProvider()
    with pytest.raises(ValueError):
        await provider.verify_webhook(body, {"content-hmac": "forged"})

    signature = base64.b64encode(hmac.new(b"cp-secret", body, hashlib.sha256).digest()).decode()
    event = await provider.verify_webhook(
        body, {"content-hmac": signature, "content-type": "application/x-www-form-urlencoded"}
    )
    assert event.status == "succeeded"
    assert event.payment_id == "pay-1"
    assert event.amount_rub == 499.0


async def test_yookassa_trusts_the_api_not_the_notification_body(monkeypatch):
    monkeypatch.setattr(settings, "yookassa_shop_id", "shop")
    monkeypatch.setattr(settings, "yookassa_secret_key", "key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/payments/yk-1"
        return httpx.Response(
            200,
            json={"id": "yk-1", "status": "canceled",
                  "amount": {"value": "499.00", "currency": "RUB"},
                  "metadata": {"payment_id": "pay-1"}},
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    forged = b'{"event": "payment.succeeded", "object": {"id": "yk-1", "status": "succeeded"}}'
    event = await YooKassaProvider().verify_webhook(forged, {})
    assert event.status == "canceled"
    assert event.payment_id == "pay-1"
    assert event.event_id == "payment.succeeded:yk-1"
