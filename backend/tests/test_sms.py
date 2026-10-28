"""SMS.ru adapter against a mocked HTTP API."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services.sms import SmsError, SmsRuProvider


def _mock(monkeypatch, body: dict) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return seen


async def test_smsru_sends_and_accepts_status_100(monkeypatch):
    monkeypatch.setattr(settings, "smsru_api_id", "api-key")
    seen = _mock(monkeypatch, {
        "status": "OK", "status_code": 100,
        "sms": {"79991234567": {"status": "OK", "status_code": 100, "sms_id": "1"}},
    })
    await SmsRuProvider().send("79991234567", "Calmap: код входа 123456.", "203.0.113.5")
    form = dict(httpx.QueryParams(seen[0].content.decode()))
    assert seen[0].url == "https://sms.ru/sms/send"
    assert form["to"] == "79991234567" and form["json"] == "1" and form["ip"] == "203.0.113.5"


async def test_smsru_refusal_raises(monkeypatch):
    monkeypatch.setattr(settings, "smsru_api_id", "api-key")
    _mock(monkeypatch, {
        "status": "OK", "status_code": 100,
        "sms": {"79991234567": {"status": "ERROR", "status_code": 207}},
    })
    with pytest.raises(SmsError):
        await SmsRuProvider().send("79991234567", "text", None)
