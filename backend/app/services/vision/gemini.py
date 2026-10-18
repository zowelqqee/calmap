"""Gemini adapter.

Chosen as the default paid provider on cost grounds: at roughly 0.07 RUB per photo it
keeps vision spend near 13% of subscription revenue, where an Opus/Sonnet-class model
would exceed it outright. Swapping providers is a config change, not a code change —
which also covers the case where a RU-hosted deployment has to fall back to YandexGPT
or GigaChat.

`LLM_PROXY_BASE_URL` exists because a backend hosted in Russia (required by 152-FZ for
personal health data) cannot reach Google's endpoints directly.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from app.core.config import settings
from app.services.llm_http import post_json
from app.services.vision.base import CatalogHint, VisionResult, build_prompt, parse_items

DEFAULT_MODEL = "gemini-2.5-flash"
GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Published per-million-token rates for gemini-2.5-flash; used for the cost telemetry
# that drives the per-tier vision limits.
INPUT_USD_PER_MTOK = 0.15
OUTPUT_USD_PER_MTOK = 1.25

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "grams": {"type": "number"},
                    "confidence": {"type": "number"},
                    "alternatives": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["slug", "grams", "confidence"],
            },
        }
    },
    "required": ["items"],
}


class GeminiVisionProvider:
    name = "gemini"

    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 30.0) -> None:
        self.model = model
        self._timeout = timeout

    @property
    def _base_url(self) -> str:
        return settings.llm_proxy_base_url.rstrip("/") or GOOGLE_BASE_URL

    async def recognize(
        self, image: bytes, mime_type: str, catalog: list[CatalogHint]
    ) -> VisionResult:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": build_prompt(catalog)},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(image).decode(),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
                "temperature": 0.1,
            },
        }

        started = time.perf_counter()
        body = await post_json(
            f"{self._base_url}/models/{self.model}:generateContent",
            # Header, not ?key=: error messages may include the URL, and a key in
            # the query string would end up in logs.
            {"x-goog-api-key": settings.gemini_api_key},
            payload,
            timeout=self._timeout,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (KeyError, IndexError, TypeError, ValueError):
            parsed = {}
        # Hallucinated slugs are dropped rather than guessed at: a wrong product
        # silently logged is worse than a missing one the user adds by hand.
        candidates = parse_items(parsed.get("items") if isinstance(parsed, dict) else None, catalog)

        usage = body.get("usageMetadata", {}) if isinstance(body, dict) else {}
        cost = (
            usage.get("promptTokenCount", 0) * INPUT_USD_PER_MTOK
            + usage.get("candidatesTokenCount", 0) * OUTPUT_USD_PER_MTOK
        ) / 1_000_000

        return VisionResult(
            provider=self.name,
            model=self.model,
            candidates=candidates,
            raw_response=body,
            latency_ms=latency_ms,
            cost_usd=round(cost, 6),
        )
