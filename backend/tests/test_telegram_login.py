"""Sign-in codes handed out by the Telegram bot."""

from __future__ import annotations

from app.core.config import settings
from tests.conftest import BOT_HEADERS, new_phone, sign_in


async def _bot_code(client, phone: str, telegram_user_id: int = 4242):
    return await client.post(
        "/v1/bot/login-code",
        json={"phone": phone, "telegram_user_id": telegram_user_id},
        headers=BOT_HEADERS,
    )


async def test_bot_code_signs_in_and_creates_account(client):
    phone = new_phone()
    issued = await _bot_code(client, phone)
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert body["account_exists"] is False and len(body["code"]) == 6
    verified = await client.post(
        "/v1/auth/phone/verify",
        json={"phone": phone, "code": body["code"], "personal_data_consent": True},
    )
    assert verified.status_code == 200, verified.text

    again = await _bot_code(client, phone)
    assert again.json()["account_exists"] is True


async def test_bot_code_works_only_for_its_number(client):
    phone, other = new_phone(), new_phone()
    code = (await _bot_code(client, phone)).json()["code"]
    wrong = await client.post(
        "/v1/auth/phone/verify",
        json={"phone": other, "code": code, "personal_data_consent": True},
    )
    assert wrong.status_code == 401


async def test_bot_code_needs_the_bot_secret(client):
    response = await client.post(
        "/v1/bot/login-code", json={"phone": new_phone(), "telegram_user_id": 1}
    )
    assert response.status_code == 401


async def test_bot_codes_are_limited_per_number(client):
    phone = new_phone()
    for _ in range(settings.phone_codes_per_hour):
        assert (await _bot_code(client, phone, 777)).status_code == 200
    limited = await _bot_code(client, phone, 777)
    assert limited.status_code == 429 and limited.headers["Retry-After"]


async def test_bot_codes_do_not_use_the_sms_budget(client, monkeypatch):
    monkeypatch.setattr(settings, "sms_daily_limit", 0)
    assert (await _bot_code(client, new_phone())).status_code == 200
    sms = await client.post("/v1/auth/phone/code", json={"phone": new_phone()})
    assert sms.status_code == 503


async def test_channels(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_username", "calmap_bot")
    body = (await client.get("/v1/auth/phone/channels")).json()
    assert body == {"sms": True, "telegram_url": "https://t.me/calmap_bot?start=login"}
    monkeypatch.setattr(settings, "telegram_bot_username", "")
    assert (await client.get("/v1/auth/phone/channels")).json()["telegram_url"] is None


async def test_without_sms_deletion_needs_recent_sign_in(client, monkeypatch):
    tokens = await sign_in(client)
    client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    monkeypatch.setattr(settings, "sms_provider", "stub")
    monkeypatch.setattr(settings, "env", "production")
    assert (await client.post("/v1/auth/phone/code", json={"phone": new_phone()})).status_code == 503
    sent = await client.post("/v1/auth/me/deletion-code")
    assert sent.status_code == 200 and sent.json()["method"] == "recent_sign_in"
    # The session started seconds ago: that confirms the deletion.
    deleted = await client.request("DELETE", "/v1/auth/me", json={})
    assert deleted.status_code == 204, deleted.text
