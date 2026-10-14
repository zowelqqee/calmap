"""SMS delivery for sign-in codes.

* `smsru` — SMS.ru HTTP API (`POST https://sms.ru/sms/send`, JSON answer; a message
  accepted for delivery has status_code 100).
* `stub` — development and tests: the message is kept in memory and logged. It is
  refused in production.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class SmsError(RuntimeError):
    pass


class StubSmsProvider:
    name = "stub"

    def __init__(self) -> None:
        #: phone → last message text; read by tests.
        self.sent: dict[str, str] = {}

    async def send(self, phone: str, text: str, ip: str | None) -> None:
        if settings.env == "production":
            raise SmsError("stub SMS provider is disabled in production")
        self.sent[phone] = text
        logger.info("SMS to %s: %s", phone, text)


class SmsRuProvider:
    name = "smsru"
    endpoint = "https://sms.ru/sms/send"

    async def send(self, phone: str, text: str, ip: str | None) -> None:
        if not settings.smsru_api_id:
            raise SmsError("SMSRU_API_ID is not configured")
        data = {"api_id": settings.smsru_api_id, "to": phone, "msg": text, "json": "1"}
        if settings.sms_sender:
            data["from"] = settings.sms_sender
        if ip:
            # SMS.ru uses the end user's IP for its own fraud limits.
            data["ip"] = ip
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.endpoint, data=data)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SmsError("SMS.ru is unavailable") from exc
        results = body.get("sms") or {}
        delivered = body.get("status") == "OK" and any(
            isinstance(item, dict) and item.get("status_code") == 100
            for item in results.values()
        )
        if not delivered:
            logger.error("SMS.ru refused a message: %s", body)
            raise SmsError("SMS.ru refused the message")


@lru_cache
def get_sms_provider() -> StubSmsProvider | SmsRuProvider:
    return SmsRuProvider() if settings.sms_provider == "smsru" else StubSmsProvider()
