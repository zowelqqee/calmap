from __future__ import annotations

import uuid

from datetime import datetime, timedelta, timezone

from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

from calmap_bot.db import Payment
from calmap_bot.handlers import normalize_phone
from calmap_bot.reminders import reminder_kind, send_reminders
from calmap_bot.web import build_app


def test_reminder_kinds():
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert reminder_kind(now + timedelta(days=2, hours=12), now) == "3d"
    assert reminder_kind(now + timedelta(hours=20), now) == "1d"
    assert reminder_kind(now + timedelta(days=5), now) is None
    assert reminder_kind(now - timedelta(hours=1), now) == "ended"
    assert reminder_kind(now - timedelta(hours=49), now) is None


def test_phone_normalisation():
    assert normalize_phone("+7 (999) 123-45-67") == "79991234567"
    assert normalize_phone("89991234567") == "79991234567"
    assert normalize_phone("79991234567") == "79991234567"
    assert normalize_phone("+380501234567") is None


async def test_reminders_are_sent_once_per_period(env, linked_user):
    until = (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat()
    env.backend.expiring_rows = [
        {"telegram_user_id": linked_user, "state": "active", "tier": "pro", "access_until": until}
    ]
    assert await send_reminders(env.db, env.backend_client, env.billing.notify, env.billing.tariffs) == 1
    assert await send_reminders(env.db, env.backend_client, env.billing.notify, env.billing.tariffs) == 0
    assert "PRO закончится" in env.sent[-1][1]


async def test_reminders_can_be_turned_off(env, linked_user):
    from calmap_bot.db import BotUser

    until = (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat()
    env.backend.expiring_rows = [
        {"telegram_user_id": linked_user, "state": "trial", "tier": "trial", "access_until": until}
    ]
    async with env.db.session() as session:
        (await session.get(BotUser, linked_user)).reminders_enabled = False
    assert await send_reminders(env.db, env.backend_client, env.billing.notify, env.billing.tariffs) == 0
    async with env.db.session() as session:
        (await session.get(BotUser, linked_user)).reminders_enabled = True
    assert await send_reminders(env.db, env.backend_client, env.billing.notify, env.billing.tariffs) == 1
    buttons = [b for row in env.markups[-1].inline_keyboard for b in row]
    assert any(b.callback_data == "reminders:off" for b in buttons)
    assert any(b.callback_data == "offer:pro" for b in buttons)


async def test_webhook_rereads_the_payment_and_delivers(env, linked_user):
    await env.billing.start_checkout(linked_user, "pro")
    async with env.db.session() as session:
        record = await session.scalar(select(Payment).where(Payment.telegram_user_id == linked_user))
    env.yoo.succeed(record.yookassa_payment_id)

    async with TestClient(TestServer(build_app(env.billing))) as client:
        # A forged body claiming success for an unknown payment changes nothing.
        forged = await client.post(
            "/yookassa/webhook",
            json={"event": "payment.succeeded", "object": {"id": str(uuid.uuid4())}},
        )
        assert forged.status == 200
        # Ids that are not YooKassa UUIDs never reach its API.
        malformed = await client.post(
            "/yookassa/webhook",
            json={"event": "payment.succeeded", "object": {"id": "../refunds/x"}},
        )
        assert malformed.status == 400
        response = await client.post(
            "/yookassa/webhook",
            json={"event": "payment.succeeded", "object": {"id": record.yookassa_payment_id, "status": "succeeded"}},
        )
        assert response.status == 200
        assert (await client.get("/health")).status == 200
    assert any(e["telegram_user_id"] == linked_user for e in env.backend.events.values())
