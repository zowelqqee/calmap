"""Client of the Calmap backend's bot API (/v1/bot/*)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx


class BackendError(RuntimeError):
    """The backend is unreachable or answered with an unexpected error."""


class NotLinked(LookupError):
    """No Calmap account for this phone / Telegram user."""


class LinkChanged(LookupError):
    """The Telegram account is now linked to another Calmap account."""


@dataclass(frozen=True, slots=True)
class Linked:
    user_id: uuid.UUID
    subscription: "SubscriptionState"


@dataclass(frozen=True, slots=True)
class SubscriptionState:
    state: str  # trial | active | trial_ended | expired | revoked
    has_access: bool
    tier: str | None
    paid_until: datetime | None
    access_until: datetime | None

    @classmethod
    def from_json(cls, data: dict) -> SubscriptionState:
        def parse(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return cls(
            state=data["state"],
            has_access=bool(data["has_access"]),
            tier=data.get("tier"),
            paid_until=parse(data.get("paid_until")),
            access_until=parse(data.get("access_until")),
        )


@dataclass(frozen=True, slots=True)
class Expiring:
    telegram_user_id: int
    state: str
    tier: str | None
    access_until: datetime


class CalmapBackend:
    def __init__(self, base_url: str, secret: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Bot-Secret": secret},
            timeout=15.0,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BackendError(f"backend unreachable: {exc.__class__.__name__}") from exc
        if response.status_code == 404:
            raise NotLinked(response.text)
        if response.status_code == 409:
            raise LinkChanged(response.text)
        if response.status_code >= 400:
            raise BackendError(f"backend answered {response.status_code}: {response.text[:200]}")
        return response.json()

    async def link(self, phone: str, telegram_user_id: int, username: str | None) -> Linked:
        body = await self._request(
            "POST",
            "/v1/bot/link",
            json={"phone": phone, "telegram_user_id": telegram_user_id, "telegram_username": username},
        )
        return Linked(uuid.UUID(body["user_id"]), SubscriptionState.from_json(body["subscription"]))

    async def unlink(self, telegram_user_id: int) -> None:
        try:
            response = await self._client.delete(f"/v1/bot/link/{telegram_user_id}")
        except httpx.HTTPError as exc:
            raise BackendError(f"backend unreachable: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise BackendError(f"backend answered {response.status_code}")

    async def status(self, telegram_user_id: int) -> SubscriptionState:
        return SubscriptionState.from_json(
            await self._request("GET", f"/v1/bot/subscription/{telegram_user_id}")
        )

    async def report_paid(
        self,
        *,
        event_id: str,
        telegram_user_id: int,
        user_id: uuid.UUID,
        tier: str,
        paid_until: datetime,
        amount: float,
    ) -> SubscriptionState:
        body = await self._request(
            "POST",
            "/v1/bot/subscription/events",
            json={
                "event_id": event_id,
                "telegram_user_id": telegram_user_id,
                "user_id": str(user_id),
                "status": "paid",
                "tier": tier,
                "paid_until": paid_until.isoformat(),
                "amount": amount,
                "currency": "RUB",
            },
        )
        return SubscriptionState.from_json(body["subscription"])

    async def report_revoked(
        self, *, event_id: str, telegram_user_id: int, user_id: uuid.UUID
    ) -> SubscriptionState:
        body = await self._request(
            "POST",
            "/v1/bot/subscription/events",
            json={
                "event_id": event_id,
                "telegram_user_id": telegram_user_id,
                "user_id": str(user_id),
                "status": "revoked",
            },
        )
        return SubscriptionState.from_json(body["subscription"])

    async def expiring(self, within_hours: int) -> list[Expiring]:
        rows = await self._request(
            "GET", "/v1/bot/subscriptions/expiring", params={"within_hours": within_hours}
        )
        return [
            Expiring(
                telegram_user_id=row["telegram_user_id"],
                state=row["state"],
                tier=row.get("tier"),
                access_until=datetime.fromisoformat(row["access_until"]),
            )
            for row in rows
        ]
