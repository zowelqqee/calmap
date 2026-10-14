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


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """A registered, authenticated but not-yet-onboarded user."""
    import uuid

    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    response = await client.post(
        "/v1/auth/register", json={"email": email, "password": "correct-horse-battery"}
    )
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client
