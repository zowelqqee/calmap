"""YooKassa API v3: payments with redirect confirmation and 54-FZ receipts.

Notifications from YooKassa are unsigned, so the bot never trusts their body: every
notification only names a payment or refund, which is then read from the API.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

API_URL = "https://api.yookassa.ru/v3"


class YooKassaError(RuntimeError):
    pass


class YooKassaNotFound(YooKassaError):
    """The id is not a payment/refund of this shop (e.g. a forged notification)."""


@dataclass(frozen=True, slots=True)
class YooPayment:
    id: str
    status: str  # pending | waiting_for_capture | succeeded | canceled
    paid: bool
    amount: Decimal
    currency: str
    confirmation_url: str | None
    metadata: dict

    @classmethod
    def from_json(cls, data: dict) -> YooPayment:
        return cls(
            id=data["id"],
            status=data["status"],
            paid=bool(data.get("paid")),
            amount=Decimal(data["amount"]["value"]),
            currency=data["amount"]["currency"],
            confirmation_url=(data.get("confirmation") or {}).get("confirmation_url"),
            metadata=data.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class YooRefund:
    id: str
    payment_id: str
    status: str  # pending | succeeded | canceled
    amount: Decimal

    @classmethod
    def from_json(cls, data: dict) -> YooRefund:
        return cls(
            id=data["id"],
            payment_id=data["payment_id"],
            status=data["status"],
            amount=Decimal(data["amount"]["value"]),
        )


class YooKassa:
    def __init__(
        self, shop_id: str, secret_key: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=API_URL, auth=(shop_id, secret_key), timeout=20.0, transport=transport
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise YooKassaError(f"YooKassa unreachable: {exc.__class__.__name__}") from exc
        if response.status_code == 404:
            raise YooKassaNotFound(path)
        if response.status_code >= 400:
            raise YooKassaError(f"YooKassa answered {response.status_code}: {response.text[:300]}")
        return response.json()

    async def create_payment(
        self,
        *,
        idempotence_key: str,
        amount_rub: Decimal,
        description: str,
        return_url: str,
        metadata: dict,
        receipt_phone: str | None,
        vat_code: int,
    ) -> YooPayment:
        value = f"{amount_rub:.2f}"
        payload: dict = {
            "amount": {"value": value, "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description[:128],
            "metadata": metadata,
        }
        if receipt_phone:
            payload["receipt"] = {
                "customer": {"phone": receipt_phone},
                "items": [
                    {
                        "description": description[:128],
                        "quantity": "1.00",
                        "amount": {"value": value, "currency": "RUB"},
                        "vat_code": vat_code,
                        "payment_subject": "service",
                        "payment_mode": "full_payment",
                    }
                ],
            }
        data = await self._call(
            "POST", "/payments", json=payload, headers={"Idempotence-Key": idempotence_key}
        )
        return YooPayment.from_json(data)

    async def get_payment(self, payment_id: str) -> YooPayment:
        return YooPayment.from_json(await self._call("GET", f"/payments/{payment_id}"))

    async def get_refund(self, refund_id: str) -> YooRefund:
        return YooRefund.from_json(await self._call("GET", f"/refunds/{refund_id}"))
