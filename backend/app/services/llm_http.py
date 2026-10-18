"""HTTP calls to AI providers (OpenAI-compatible chat, Gemini).

One place for what every provider call needs:

* the egress proxy (OPENAI_PROXY_URL) — Russian servers reach OpenAI and Google
  only through a proxy abroad; nothing else in the backend uses it;
* one retry of a transient failure (connection error, timeout, 429 rate limit,
  5xx), never of a 4xx that will fail again (bad key, unknown model, no quota);
* errors as RuntimeError carrying the HTTP status and the provider's error code,
  never the API key or the proxy credentials, so callers answer 503 and the log
  says what to fix (insufficient_quota, model_not_found, invalid_api_key…).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Overridden in tests with an httpx.MockTransport.
transport: httpx.AsyncBaseTransport | None = None

RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_DELAY = 1.5


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}

    @property
    def error(self) -> dict:
        error = self.body.get("error")
        return error if isinstance(error, dict) else {}


def _client(timeout: float) -> httpx.AsyncClient:
    options: dict = {"timeout": timeout}
    if transport is not None:
        options["transport"] = transport
    elif settings.openai_proxy_url:
        # Only this client uses the proxy; trust_env=False ignores system proxies.
        options.update(proxy=settings.openai_proxy_url, trust_env=False)
    return httpx.AsyncClient(**options)


def _describe(status: int, body: dict) -> str:
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = error.get("code") or error.get("status") or error.get("type") or ""
    message = str(error.get("message") or "")[:200]
    return f"provider answered {status} {code}: {message}".strip()


async def post_json(url: str, headers: dict[str, str], payload: dict, timeout: float) -> dict:
    """POST JSON and return the decoded JSON answer, or raise ProviderError."""
    for attempt in (1, 2):
        try:
            async with _client(timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            if attempt == 1:
                logger.warning("AI provider unreachable (%s); retrying", exc.__class__.__name__)
                await asyncio.sleep(RETRY_DELAY)
                continue
            raise ProviderError(f"provider unreachable: {exc.__class__.__name__}") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if response.status_code < 400:
            if not body:
                raise ProviderError(f"provider answered {response.status_code} without JSON")
            return body
        quota_exhausted = isinstance(body.get("error"), dict) and (
            body["error"].get("code") == "insufficient_quota"
        )
        if attempt == 1 and response.status_code in RETRY_STATUSES and not quota_exhausted:
            logger.warning("AI provider answered %s; retrying", response.status_code)
            await asyncio.sleep(RETRY_DELAY)
            continue
        raise ProviderError(_describe(response.status_code, body), response.status_code, body)
    raise AssertionError("unreachable")
