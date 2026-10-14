"""152-FZ consents: separate personal-data consent, health data, AI transfer."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import pay
from tests.test_api_flow import ONBOARDING_STEPS, complete_onboarding


def _email() -> str:
    return f"consent-{uuid.uuid4().hex[:10]}@example.com"


async def test_registration_requires_the_separate_consent(client: AsyncClient):
    refused = await client.post(
        "/v1/auth/register", json={"email": _email(), "password": "correct-horse-battery"}
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == "personal data consent is required"

    accepted = await client.post(
        "/v1/auth/register",
        json={"email": _email(), "password": "correct-horse-battery",
              "personal_data_consent": True},
        headers={"User-Agent": "calmap-test/1.0"},
    )
    assert accepted.status_code == 201
    consents = await client.get(
        "/v1/me/consents",
        headers={"Authorization": f"Bearer {accepted.json()['access_token']}"},
    )
    [record] = consents.json()
    assert record["document"] == "personal_data"
    assert record["page"] == "consent"
    assert record["version"] == record["current_version"]


async def test_new_vk_account_requires_consent(client: AsyncClient):
    subject = f"test:{uuid.uuid4().hex}"
    refused = await client.post("/v1/auth/oauth/vk", json={"id_token": subject})
    assert refused.status_code == 422
    created = await client.post(
        "/v1/auth/oauth/vk", json={"id_token": subject, "personal_data_consent": True}
    )
    assert created.status_code == 200
    # Signing in again to the existing account does not ask again.
    again = await client.post("/v1/auth/oauth/vk", json={"id_token": subject})
    assert again.status_code == 200


async def test_foreign_sign_in_providers_are_not_offered(client: AsyncClient):
    for provider in ("google", "apple"):
        response = await client.post(
            f"/v1/auth/oauth/{provider}",
            json={"id_token": "test:x", "personal_data_consent": True},
        )
        assert response.status_code == 400


async def test_health_data_needs_its_own_consent(client: AsyncClient):
    registered = await client.post(
        "/v1/auth/register",
        json={"email": _email(), "password": "correct-horse-battery",
              "personal_data_consent": True},
    )
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    personal = ONBOARDING_STEPS[0][1]
    blocked = await client.patch("/v1/onboarding/personal", json=personal, headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["document"] == "health_data"

    given = await client.post(
        "/v1/me/consents", json={"document": "health_data"}, headers=headers
    )
    assert given.status_code == 201
    saved = await client.patch("/v1/onboarding/personal", json=personal, headers=headers)
    assert saved.status_code == 200


async def test_ai_consultant_asks_for_transfer_consent(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    await pay(auth_client, "pro")
    question = {"message": "Сколько белка в день?"}
    blocked = await auth_client.post("/v1/assistant/chat", json=question)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["document"] == "ai_assistant"

    await auth_client.post("/v1/me/consents", json={"document": "ai_assistant"})
    assert (await auth_client.post("/v1/assistant/chat", json=question)).status_code == 200

    withdrawn = await auth_client.delete("/v1/me/consents/ai_assistant")
    assert withdrawn.status_code == 204
    assert (await auth_client.post("/v1/assistant/chat", json=question)).status_code == 409


async def test_account_level_consents_are_withdrawn_by_deleting_the_account(
    auth_client: AsyncClient,
):
    response = await auth_client.delete("/v1/me/consents/personal_data")
    assert response.status_code == 400
    assert "удаление аккаунта" in response.json()["detail"]


async def test_deletion_is_recorded_without_contact_data(auth_client: AsyncClient):
    from app.db.session import SessionLocal

    user_id = (await auth_client.get("/v1/auth/me")).json()["id"]
    assert (await auth_client.delete("/v1/auth/me")).status_code == 204
    async with SessionLocal() as session:
        row = (
            await session.execute(
                text("SELECT reason, categories FROM account_deletions WHERE user_ref = :id"),
                {"id": user_id},
            )
        ).one()
        consents_left = await session.scalar(
            text("SELECT count(*) FROM user_consents WHERE user_id = :id"), {"id": user_id}
        )
    assert row.reason == "user_request"
    assert "дневник питания" in row.categories
    assert consents_left == 0
