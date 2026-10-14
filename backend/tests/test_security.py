"""Regression tests for the security review: sessions, SMS limits, test sign-in,
input bounds and the planner's worst case."""

from __future__ import annotations

import time
from datetime import date, timedelta

from httpx import AsyncClient

from app.core.config import settings
from app.domain.solver.menu import _can_assign_distinct
from app.services.phone_auth import network_key, normalize_phone
from tests.conftest import BOT_HEADERS, new_phone, sign_in


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ sessions


async def test_refresh_rotates_and_a_replayed_token_ends_the_session(client: AsyncClient):
    first = await sign_in(client)
    rotated = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]
    # Rotate once more: the first token is now two generations old.
    third = (
        await client.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    ).json()

    replay = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    # The copy was detected: the whole session is gone, the owner's tokens included.
    assert (await client.get("/v1/auth/me", headers=_bearer(third["access_token"]))).status_code == 401
    assert (
        await client.post("/v1/auth/refresh", json={"refresh_token": third["refresh_token"]})
    ).status_code == 401


async def test_lost_refresh_answer_can_be_retried_once(client: AsyncClient):
    tokens = await sign_in(client)
    lost = await client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert lost.status_code == 200
    # The app never saw the answer and repeats the request with the same token.
    retried = await client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert retried.status_code == 200
    assert (await client.get("/v1/auth/me", headers=_bearer(retried.json()["access_token"]))).status_code == 200


async def test_logout_ends_only_this_device_unless_everywhere(client: AsyncClient):
    phone = new_phone()
    phone_a = await sign_in(client, phone)
    phone_b = await sign_in(client, phone)

    out = await client.post("/v1/auth/logout", headers=_bearer(phone_a["access_token"]))
    assert out.status_code == 204
    assert (await client.get("/v1/auth/me", headers=_bearer(phone_a["access_token"]))).status_code == 401
    assert (
        await client.post("/v1/auth/refresh", json={"refresh_token": phone_a["refresh_token"]})
    ).status_code == 401
    assert (await client.get("/v1/auth/me", headers=_bearer(phone_b["access_token"]))).status_code == 200

    phone_c = await sign_in(client, phone)
    everywhere = await client.post(
        "/v1/auth/logout", params={"everywhere": "true"}, headers=_bearer(phone_c["access_token"])
    )
    assert everywhere.status_code == 204
    assert (await client.get("/v1/auth/me", headers=_bearer(phone_b["access_token"]))).status_code == 401


# --------------------------------------------------------------- SMS limits


def test_phone_normalisation_accepts_ascii_digits_only():
    assert normalize_phone("+7 999 123-45-67") == "79991234567"
    assert normalize_phone("79９９９１２３４５６") is None
    assert normalize_phone("7٩٩٩١٢٣٤٥٦٧") is None


def test_limits_count_ipv6_by_network():
    assert network_key("2001:db8:1:2::1") == network_key("2001:db8:1:2:ffff::9")
    assert network_key("2001:db8:1:3::1") != network_key("2001:db8:1:2::1")
    assert network_key("::ffff:10.0.0.1") == "10.0.0.1"
    assert network_key("testclient") is None


async def test_one_network_cannot_drain_the_sms_budget(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "sms_per_network_daily", 0)
    refused = await client.post("/v1/auth/phone/code", json={"phone": new_phone()})
    assert refused.status_code == 429


async def test_strangers_requests_do_not_use_up_the_owners_allowance(client: AsyncClient, monkeypatch):
    from app.db.models import PhoneCode
    from app.db.session import SessionLocal
    from app.services.phone_auth import _hash

    phone = new_phone()
    # Five codes requested for this number from another network this hour.
    async with SessionLocal() as session:
        for _ in range(settings.phone_codes_per_hour):
            session.add(
                PhoneCode(
                    phone=phone,
                    code_hash=_hash(phone, "000000"),
                    expires_at=settings_now() + timedelta(minutes=5),
                    ip_address="203.0.113.7",
                )
            )
        await session.commit()
    assert (await client.post("/v1/auth/phone/code", json={"phone": phone})).status_code == 200


def settings_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


# ------------------------------------------------------------- test sign-in


async def test_test_tokens_never_map_onto_real_vk_accounts(monkeypatch):
    from app.services.oauth import OAuthVerificationError, verify_oauth_token

    subject, _ = await verify_oauth_token("vk", "test:12345")
    assert subject == "vktest:12345"
    for env in ("staging", "production"):
        monkeypatch.setattr(settings, "env", env)
        try:
            await verify_oauth_token("vk", "test:12345")
        except OAuthVerificationError:
            pass
        else:
            raise AssertionError(f"test token accepted in {env}")


def test_safe_defaults_without_env():
    from app.core.config import Settings

    fields = Settings.model_fields
    assert fields["env"].default == "production"
    assert fields["debug"].default is False


# ------------------------------------------------------------------- bounds


def test_meal_slots_are_bounded():
    import pytest
    from pydantic import ValidationError

    from app.schemas.plan import GeneratePlanRequest

    with pytest.raises(ValidationError):
        GeneratePlanRequest(meal_slots=["breakfast"] * 7)
    assert len(GeneratePlanRequest(meal_slots=["breakfast"] * 6).meal_slots) == 6


def test_distinct_assignment_is_fast_when_recipes_run_short():
    class R:
        def __init__(self, i: int) -> None:
            self.id = f"r{i}"

    recipes = [R(i) for i in range(21)]
    started = time.perf_counter()
    # 22 slots over 21 recipes: impossible, and brute force would never finish.
    assert _can_assign_distinct([recipes] * 22) is False
    assert _can_assign_distinct([recipes] * 21) is True
    assert time.perf_counter() - started < 1


async def test_workout_dates_are_bounded(auth_client: AsyncClient):
    far = date.today() + timedelta(days=5000)
    response = await auth_client.get(
        "/v1/workouts/calendar",
        params={"date_from": far.isoformat(), "date_to": far.isoformat()},
    )
    assert response.status_code in (409, 422)


async def test_non_ascii_bot_secret_is_401_not_500(client: AsyncClient):
    response = await client.get(
        "/v1/bot/subscription/1", headers={"X-Bot-Secret": "секрет".encode()}
    )
    assert response.status_code == 401
    assert BOT_HEADERS  # the valid secret stays usable elsewhere


# ---------------------------------------------------------- account deletion


async def test_deletion_needs_the_sms_code(auth_client: AsyncClient):
    from tests.conftest import last_sms_code

    assert (await auth_client.delete("/v1/auth/me")).status_code == 403
    sent = await auth_client.post("/v1/auth/me/deletion-code")
    assert sent.status_code == 200
    body = sent.json()
    assert body["method"] == "sms"
    assert body["phone_masked"].endswith(auth_client.phone[-2:])
    assert "***" in body["phone_masked"]
    assert "УДАЛЕНИЯ" in _last_sms(auth_client.phone)

    code = last_sms_code(auth_client.phone)
    wrong = "000000" if code != "000000" else "111111"
    # A wrong code is 403, not 401: the app must not take it for an expired session.
    refused = await auth_client.request("DELETE", "/v1/auth/me", json={"code": wrong})
    assert refused.status_code == 403
    assert (await auth_client.get("/v1/auth/me")).status_code == 200

    deleted = await auth_client.request("DELETE", "/v1/auth/me", json={"code": code})
    assert deleted.status_code == 204
    assert (await auth_client.get("/v1/auth/me")).status_code == 401


async def test_sign_in_and_deletion_codes_do_not_mix(client: AsyncClient):
    from tests.conftest import last_sms_code

    tokens = await sign_in(client)
    phone = tokens["phone"]
    headers = _bearer(tokens["access_token"])
    # A fresh sign-in code cannot delete the account.
    await client.post("/v1/auth/phone/code", json={"phone": phone})
    sign_in_code = last_sms_code(phone)
    refused = await client.request(
        "DELETE", "/v1/auth/me", json={"code": sign_in_code}, headers=headers
    )
    assert refused.status_code == 403
    # A deletion code cannot sign in, and requesting it keeps the sign-in code valid.
    await client.post("/v1/auth/me/deletion-code", headers=headers)
    deletion_code = last_sms_code(phone)
    as_sign_in = await client.post(
        "/v1/auth/phone/verify", json={"phone": phone, "code": deletion_code}
    )
    if deletion_code != sign_in_code:
        assert as_sign_in.status_code == 401
    still_valid = await client.post(
        "/v1/auth/phone/verify", json={"phone": phone, "code": sign_in_code}
    )
    assert still_valid.status_code == 200


async def test_account_without_phone_confirms_by_recent_sign_in(client: AsyncClient):
    import uuid as uuid_module

    from sqlalchemy import update

    from app.core.security import decode_token
    from app.db.models import AuthSession
    from app.db.session import SessionLocal

    async def vk_session() -> dict:
        response = await client.post(
            "/v1/auth/oauth/vk",
            json={"id_token": f"test:{subject}", "personal_data_consent": True},
        )
        assert response.status_code == 200, response.text
        return _bearer(response.json()["access_token"])

    subject = uuid_module.uuid4().hex
    old = await vk_session()
    sent = await client.post("/v1/auth/me/deletion-code", headers=old)
    assert sent.json() == {
        "method": "recent_sign_in", "phone_masked": None, "expires_in": None, "resend_in": None
    }
    # Make that session older than the confirmation window.
    async with SessionLocal() as session:
        claims = decode_token(old["Authorization"].removeprefix("Bearer "), "access")
        await session.execute(
            update(AuthSession)
            .where(AuthSession.id == claims.session_id)
            .values(created_at=settings_now() - timedelta(hours=1))
        )
        await session.commit()
    assert (await client.delete("/v1/auth/me", headers=old)).status_code == 403

    fresh = await vk_session()
    assert (await client.delete("/v1/auth/me", headers=fresh)).status_code == 204


def _last_sms(phone: str) -> str:
    from app.services.sms import get_sms_provider

    return get_sms_provider().sent[normalize_phone(phone)]
