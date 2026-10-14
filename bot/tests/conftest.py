"""Bot tests run against a real PostgreSQL (database calmap_bot_test) with fake
YooKassa and Calmap backends served through httpx.MockTransport."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import psycopg
import pytest
import pytest_asyncio

from calmap_bot.backend import CalmapBackend
from calmap_bot.billing import Billing
from calmap_bot.config import Settings
from calmap_bot.db import BotUser, Database
from calmap_bot.tariffs import tariffs
from calmap_bot.yookassa import YooKassa

TEST_DB = "calmap_bot_test"


@pytest.fixture(scope="session", autouse=True)
def database_url() -> str:
    with psycopg.connect("postgresql://localhost:5432/postgres", autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    return f"postgresql+asyncpg://localhost:5432/{TEST_DB}"


@pytest_asyncio.fixture(scope="session")
async def db(database_url: str) -> Database:
    database = Database(database_url)
    await database.create_schema()
    yield database
    await database.dispose()


class FakeYooKassa:
    """In-memory YooKassa: payments, refunds and request log."""

    def __init__(self) -> None:
        self.payments: dict[str, dict] = {}
        self.refunds: dict[str, dict] = {}
        self.created: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v3/payments":
            body = json.loads(request.content)
            payment_id = f"yk-{uuid.uuid4().hex[:12]}"
            self.created.append({**body, "idempotence_key": request.headers["Idempotence-Key"]})
            self.payments[payment_id] = {
                "id": payment_id,
                "status": "pending",
                "paid": False,
                "amount": body["amount"],
                "confirmation": {"type": "redirect", "confirmation_url": f"https://yoomoney.example/{payment_id}"},
                "metadata": body["metadata"],
            }
            return httpx.Response(200, json=self.payments[payment_id])
        if request.method == "GET" and request.url.path.startswith("/v3/payments/"):
            payment = self.payments.get(request.url.path.rsplit("/", 1)[1])
            return httpx.Response(200, json=payment) if payment else httpx.Response(404, json={})
        if request.method == "GET" and request.url.path.startswith("/v3/refunds/"):
            return httpx.Response(200, json=self.refunds[request.url.path.rsplit("/", 1)[1]])
        return httpx.Response(404)

    def succeed(self, payment_id: str, amount: str | None = None) -> None:
        payment = self.payments[payment_id]
        payment.update(status="succeeded", paid=True)
        if amount:
            payment["amount"] = {"value": amount, "currency": "RUB"}

    def refund(self, payment_id: str, amount: str) -> str:
        refund_id = f"rf-{uuid.uuid4().hex[:12]}"
        self.refunds[refund_id] = {
            "id": refund_id,
            "payment_id": payment_id,
            "status": "succeeded",
            "amount": {"value": amount, "currency": "RUB"},
        }
        return refund_id


class FakeBackend:
    """The Calmap /v1/bot/* API with one subscription per Telegram user."""

    def __init__(self) -> None:
        self.phones: dict[str, int] = {}
        self.subs: dict[int, dict] = {}
        self.events: dict[str, dict] = {}
        self.fail_events = False

    def add_account(self, phone: str, telegram_user_id: int, **sub) -> None:
        self.phones[phone] = telegram_user_id
        self.subs[telegram_user_id] = {
            "state": "trial", "has_access": True, "tier": "trial",
            "paid_until": None, "access_until": "2030-01-01T00:00:00+00:00", **sub,
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Bot-Secret"] == "secret"
        path = request.url.path
        if path == "/v1/bot/link":
            body = json.loads(request.content)
            if body["phone"] not in self.phones:
                return httpx.Response(404, json={"detail": "no account with this phone"})
            return httpx.Response(200, json={"user_id": "u", "subscription": self.subs[body["telegram_user_id"]]})
        if path.startswith("/v1/bot/subscription/") and request.method == "GET":
            telegram_user_id = int(path.rsplit("/", 1)[1])
            if telegram_user_id not in self.subs:
                return httpx.Response(404, json={"detail": "telegram account is not linked"})
            return httpx.Response(200, json=self.subs[telegram_user_id])
        if path == "/v1/bot/subscription/events":
            if self.fail_events:
                return httpx.Response(503, json={"detail": "down"})
            body = json.loads(request.content)
            telegram_user_id = body["telegram_user_id"]
            if telegram_user_id not in self.subs:
                return httpx.Response(404, json={"detail": "not linked"})
            processed = body["event_id"] not in self.events
            if processed:
                self.events[body["event_id"]] = body
                if body["status"] == "paid":
                    self.subs[telegram_user_id] = {
                        "state": "active", "has_access": True, "tier": body["tier"],
                        "paid_until": body["paid_until"], "access_until": body["paid_until"],
                    }
                else:
                    now = datetime.now(timezone.utc).isoformat()
                    self.subs[telegram_user_id] = {
                        "state": "revoked", "has_access": False, "tier": self.subs[telegram_user_id]["tier"],
                        "paid_until": now, "access_until": None,
                    }
            return httpx.Response(200, json={"processed": processed, "subscription": self.subs[telegram_user_id]})
        if path == "/v1/bot/subscriptions/expiring":
            return httpx.Response(200, json=getattr(self, "expiring_rows", []))
        return httpx.Response(404)


@pytest_asyncio.fixture
async def env(db: Database):
    settings = Settings(_env_file=None, price_base_rub=299, price_pro_rub=499, subscription_days=30)
    yoo_fake, backend_fake = FakeYooKassa(), FakeBackend()
    yookassa = YooKassa("shop", "key", transport=httpx.MockTransport(yoo_fake.handler))
    backend = CalmapBackend("http://backend", "secret", transport=httpx.MockTransport(backend_fake.handler))
    sent: list[tuple[int, str]] = []

    async def notify(telegram_user_id: int, text: str) -> None:
        sent.append((telegram_user_id, text))

    billing = Billing(
        db, yookassa, backend, notify,
        tariffs=tariffs(settings), return_url="https://t.me/calmap_pay_bot",
        send_receipts=True, vat_code=1,
    )

    class Env:
        pass

    e = Env()
    e.db, e.yoo, e.backend, e.billing, e.sent, e.backend_client = db, yoo_fake, backend_fake, billing, sent, backend
    yield e
    await yookassa.close()
    await backend.close()


_ids = iter(range(5_000_000, 6_000_000))


@pytest_asyncio.fixture
async def linked_user(env) -> int:
    telegram_user_id = next(_ids)
    phone = f"7999{telegram_user_id:07d}"
    env.backend.add_account(phone, telegram_user_id)
    async with env.db.session() as session:
        session.add(BotUser(telegram_user_id=telegram_user_id, phone=phone))
    return telegram_user_id


def rub(value: int) -> Decimal:
    return Decimal(value)
