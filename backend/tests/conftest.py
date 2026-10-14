"""Integration test harness.

Runs against a real Postgres database (`calmap_test`) created and migrated from the
same Alembic history as production. Using create_all here instead would let the models
and the migrations drift apart silently, which is exactly the bug integration tests
exist to catch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Must happen before anything imports app.core.config.
TEST_DB = "calmap_test"
os.environ["DATABASE_URL"] = f"postgresql+asyncpg://localhost:5432/{TEST_DB}"
os.environ["ENV"] = "local"
os.environ["VISION_PROVIDER"] = "stub"
os.environ["SECRET_KEY"] = "test-secret-key-not-used-anywhere-else"
os.environ["AUTH_RATE_LIMIT_PER_MINUTE"] = "0"
# Tests sign the same number in repeatedly; the resend pause has its own test.
os.environ["PHONE_CODE_RESEND_SECONDS"] = "0"
os.environ["TELEGRAM_BOT_API_SECRET"] = "test-bot-secret-0123456789abcdef0123456789"
BOT_HEADERS = {"X-Bot-Secret": os.environ["TELEGRAM_BOT_API_SECRET"]}

import psycopg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _recreate_database() -> None:
    with psycopg.connect("postgresql://localhost:5432/postgres", autocommit=True) as conn:
        conn.execute(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{TEST_DB}' AND pid <> pg_backend_pid()"
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    _recreate_database()
    subprocess.run(
        [str(BACKEND_ROOT / ".venv/bin/alembic"), "upgrade", "head"],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        env={**os.environ},
    )


@pytest_asyncio.fixture(scope="session", autouse=True)
async def catalogue(database: None) -> None:
    from app.seed.run import main as seed_main

    await seed_main()


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client


_phones = iter(range(79_000_000_000, 79_999_999_999, 7))
_telegram_ids = iter(range(10_000_000, 99_999_999))


def new_phone() -> str:
    return str(next(_phones))


def last_sms_code(phone: str) -> str:
    """The code the stub SMS provider 'sent' to this number."""
    import re

    from app.services.phone_auth import normalize_phone
    from app.services.sms import get_sms_provider

    message = get_sms_provider().sent[normalize_phone(phone)]
    return re.search(r"\d{6}", message).group(0)


async def sign_in(client: AsyncClient, phone: str | None = None, consent: bool = True) -> dict:
    """Request an SMS code and exchange it for tokens, as the app does."""
    phone = phone or new_phone()
    sent = await client.post("/v1/auth/phone/code", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    response = await client.post(
        "/v1/auth/phone/verify",
        json={"phone": phone, "code": last_sms_code(phone), "personal_data_consent": consent},
    )
    assert response.status_code == 200, response.text
    return {**response.json(), "phone": phone}


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """A signed-in but not-yet-onboarded user who has given the personal-data and
    health-data consents."""
    tokens = await sign_in(client)
    client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    client.phone = tokens["phone"]  # type: ignore[attr-defined]
    consent = await client.post("/v1/me/consents", json={"document": "health_data"})
    assert consent.status_code == 201, consent.text
    return client


async def link_telegram(client: AsyncClient) -> int:
    """Link a Telegram account by the user's phone, as the bot does after the user
    shares their contact."""
    telegram_user_id = next(_telegram_ids)
    response = await client.post(
        "/v1/bot/link",
        json={"phone": client.phone, "telegram_user_id": telegram_user_id},
        headers=BOT_HEADERS,
    )
    assert response.status_code == 200, response.text
    return telegram_user_id


async def pay(client: AsyncClient, tier: str, days: int = 30) -> int:
    """Link Telegram and report a paid period, as the payment bot will."""
    import uuid
    from datetime import datetime, timedelta, timezone

    telegram_user_id = await link_telegram(client)
    response = await client.post(
        "/v1/bot/subscription/events",
        json={
            "event_id": f"test-{uuid.uuid4().hex}",
            "telegram_user_id": telegram_user_id,
            "status": "paid",
            "tier": tier,
            "paid_until": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
            "amount": 499,
            "currency": "RUB",
        },
        headers=BOT_HEADERS,
    )
    assert response.status_code == 200, response.text
    return telegram_user_id
