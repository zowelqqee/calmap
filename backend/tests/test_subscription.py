"""Subscription status from the Telegram bot and the access gate built on it."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import BOT_HEADERS, link_telegram, pay
from tests.test_api_flow import complete_onboarding


async def _set_subscription(client: AsyncClient, **values) -> None:
    from app.db.session import SessionLocal

    user_id = (await client.get("/v1/auth/me")).json()["id"]
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    async with SessionLocal() as session:
        await session.execute(
            text(f"UPDATE subscriptions SET {assignments} WHERE user_id = :user_id"),
            {**values, "user_id": user_id},
        )
        await session.commit()


def _event(telegram_user_id: int, **overrides) -> dict:
    return {
        "event_id": f"evt-{uuid.uuid4().hex}",
        "telegram_user_id": telegram_user_id,
        "status": "paid",
        "tier": "pro",
        "paid_until": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        **overrides,
    }


async def test_new_account_starts_with_a_three_day_trial(auth_client: AsyncClient):
    subscription = (await auth_client.get("/v1/me/subscription")).json()
    assert subscription["state"] == "trial"
    assert subscription["has_access"] is True
    assert subscription["tier"] == "trial"
    assert subscription["days_left"] == 3
    assert subscription["payment_status"] == "none"
    assert subscription["telegram_linked"] is False
    assert subscription["payment_available"] is True
    assert subscription["message"] is None


async def test_ended_trial_blocks_features_but_not_the_account(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    await _set_subscription(auth_client, trial_ends_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    subscription = (await auth_client.get("/v1/me/subscription")).json()
    assert subscription["state"] == "trial_ended"
    assert subscription["has_access"] is False
    assert "Пробный период закончился" in subscription["message"]

    for path in ("/v1/meal-plans/current", "/v1/me/targets", "/v1/progress/overview"):
        blocked = await auth_client.get(path)
        assert blocked.status_code == 402, path
        assert blocked.json()["detail"]["code"] == "subscription_required"
        assert blocked.json()["detail"]["state"] == "trial_ended"
    assert (await auth_client.post("/v1/onboarding/complete")).status_code == 402

    # Account management keeps working without a subscription.
    assert (await auth_client.get("/v1/auth/me")).status_code == 200
    assert (await auth_client.get("/v1/onboarding/session")).status_code == 200
    assert (await auth_client.post("/v1/me/subscription/telegram-link")).status_code == 201


async def test_bot_payment_grants_the_tier_and_repeats_are_ignored(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    telegram_user_id = await link_telegram(auth_client)
    assert (await auth_client.get("/v1/me/subscription")).json()["telegram_linked"] is True

    event = _event(telegram_user_id, tier="base", amount=299, currency="rub")
    first = await auth_client.post("/v1/bot/subscription/events", json=event, headers=BOT_HEADERS)
    second = await auth_client.post("/v1/bot/subscription/events", json=event, headers=BOT_HEADERS)
    assert first.status_code == 200, first.text
    assert first.json()["processed"] is True
    assert second.json()["processed"] is False

    subscription = (await auth_client.get("/v1/me/subscription")).json()
    assert subscription["state"] == "active"
    assert subscription["tier"] == "base"
    assert subscription["payment_status"] == "paid"
    assert subscription["days_left"] == 30
    assert subscription["limits"]["assistant_messages_per_month"] == 0
    assert (await auth_client.get("/v1/auth/me")).json()["tier"] == "base"


async def test_revoked_payment_closes_access(auth_client: AsyncClient):
    telegram_user_id = await pay(auth_client, "pro")
    revoked = await auth_client.post(
        "/v1/bot/subscription/events",
        json={"event_id": f"refund-{uuid.uuid4().hex}", "telegram_user_id": telegram_user_id,
              "status": "revoked"},
        headers=BOT_HEADERS,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["subscription"]["state"] == "revoked"
    assert (await auth_client.get("/v1/diary/2026-10-14")).status_code == 402


async def test_lapsed_period_is_stored_as_expired(auth_client: AsyncClient):
    from app.db.session import SessionLocal

    await pay(auth_client, "pro")
    await _set_subscription(auth_client, paid_until=datetime.now(timezone.utc) - timedelta(hours=1))
    subscription = (await auth_client.get("/v1/me/subscription")).json()
    assert subscription["state"] == "expired"
    assert subscription["payment_status"] == "expired"
    assert "Подписка закончилась" in subscription["message"]

    user_id = (await auth_client.get("/v1/auth/me")).json()["id"]
    async with SessionLocal() as session:
        stored = await session.scalar(
            text("SELECT payment_status FROM subscriptions WHERE user_id = :id"), {"id": user_id}
        )
    assert stored == "expired"
    # A lapsed payer does not get a second trial.
    assert (await auth_client.get("/v1/meal-plans/current")).status_code == 402


async def test_link_codes_are_single_use(auth_client: AsyncClient, client: AsyncClient):
    link = (await auth_client.post("/v1/me/subscription/telegram-link")).json()
    assert link["url"].startswith("https://t.me/calmap_test_bot?start=")
    code = link["url"].split("start=", 1)[1]
    body = {"code": code, "telegram_user_id": 424242001}
    assert (await client.post("/v1/bot/link", json=body, headers=BOT_HEADERS)).status_code == 200
    again = await client.post("/v1/bot/link", json=body, headers=BOT_HEADERS)
    assert again.status_code == 404


async def test_a_new_code_invalidates_the_previous_one(auth_client: AsyncClient):
    first = (await auth_client.post("/v1/me/subscription/telegram-link")).json()["url"]
    await auth_client.post("/v1/me/subscription/telegram-link")
    stale = await auth_client.post(
        "/v1/bot/link",
        json={"code": first.split("start=", 1)[1], "telegram_user_id": 424242002},
        headers=BOT_HEADERS,
    )
    assert stale.status_code == 404


async def test_bot_api_requires_the_shared_secret(client: AsyncClient, monkeypatch):
    from app.core.config import settings

    body = {"code": "x" * 16, "telegram_user_id": 1}
    assert (await client.post("/v1/bot/link", json=body)).status_code == 401
    wrong = await client.post("/v1/bot/link", json=body, headers={"X-Bot-Secret": "nope"})
    assert wrong.status_code == 401
    monkeypatch.setattr(settings, "telegram_bot_api_secret", "")
    assert (await client.post("/v1/bot/link", json=body, headers=BOT_HEADERS)).status_code == 404


async def test_invalid_paid_events_are_rejected(auth_client: AsyncClient):
    telegram_user_id = await link_telegram(auth_client)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    for overrides in ({"paid_until": past}, {"paid_until": None}, {"tier": None}):
        response = await auth_client.post(
            "/v1/bot/subscription/events",
            json=_event(telegram_user_id, **overrides),
            headers=BOT_HEADERS,
        )
        assert response.status_code == 422, overrides
    unlinked = await auth_client.post(
        "/v1/bot/subscription/events", json=_event(987654321), headers=BOT_HEADERS
    )
    assert unlinked.status_code == 404


async def test_relinking_a_telegram_account_moves_it(client: AsyncClient):
    from tests.conftest import _telegram_ids  # noqa: F401 — keeps ids unique across tests

    tokens = []
    for _ in range(2):
        registered = await client.post(
            "/v1/auth/register",
            json={"email": f"relink-{uuid.uuid4().hex[:10]}@example.com",
                  "password": "correct-horse-battery", "personal_data_consent": True},
        )
        tokens.append({"Authorization": f"Bearer {registered.json()['access_token']}"})
    for headers in tokens:
        url = (await client.post("/v1/me/subscription/telegram-link", headers=headers)).json()["url"]
        linked = await client.post(
            "/v1/bot/link",
            json={"code": url.split("start=", 1)[1], "telegram_user_id": 555000111},
            headers=BOT_HEADERS,
        )
        assert linked.status_code == 200
    first = (await client.get("/v1/me/subscription", headers=tokens[0])).json()
    second = (await client.get("/v1/me/subscription", headers=tokens[1])).json()
    assert first["telegram_linked"] is False
    assert second["telegram_linked"] is True


async def test_expiring_lists_accounts_for_bot_reminders(auth_client: AsyncClient):
    telegram_user_id = await pay(auth_client, "base", days=30)
    await _set_subscription(auth_client, paid_until=datetime.now(timezone.utc) + timedelta(hours=5))
    expiring = await auth_client.get(
        "/v1/bot/subscriptions/expiring", params={"within_hours": 24}, headers=BOT_HEADERS
    )
    assert expiring.status_code == 200
    entry = next(e for e in expiring.json() if e["telegram_user_id"] == telegram_user_id)
    assert entry["state"] == "active" and entry["tier"] == "base"

    status = await auth_client.get(
        f"/v1/bot/subscription/{telegram_user_id}", headers=BOT_HEADERS
    )
    assert status.json()["state"] == "active"


async def test_account_deletion_removes_the_telegram_link(auth_client: AsyncClient):
    telegram_user_id = await pay(auth_client, "pro")
    assert (await auth_client.delete("/v1/auth/me")).status_code == 204
    status = await auth_client.get(
        f"/v1/bot/subscription/{telegram_user_id}", headers=BOT_HEADERS
    )
    assert status.status_code == 404
