"""OpenAI-compatible vision adapter.

Works with OpenAI, an egress gateway, or a compatible local/provider endpoint. The
closed-catalogue prompt and post-validation are shared with Gemini, so changing the
provider cannot cause the model to become the source of nutrition numbers.
"""

from __future__ import annotations

import base64
import json
import time

from app.core.config import settings
from app.services.llm_http import ProviderError, adjust_for_model, post_json
from app.services.vision.base import CatalogHint, VisionResult, build_prompt, parse_items


class OpenAICompatibleVisionProvider:
    name = "openai_compatible"

    def __init__(self) -> None:
        self.model = settings.vision_model

    async def recognize(self, image: bytes, mime_type: str, catalog: list[CatalogHint]) -> VisionResult:
        if not settings.vision_api_key or not settings.vision_base_url:
            raise RuntimeError("VISION_API_KEY and VISION_BASE_URL are required")
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": settings.vision_max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": build_prompt(catalog)},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Распознай продукты на этом фото и верни JSON."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64.b64encode(image).decode()}",
                                "detail": settings.vision_image_detail,
                            },
                        },
                    ],
                },
            ],
        }
        started = time.perf_counter()
        url = f"{settings.vision_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {settings.vision_api_key}"}
        # Newer models take max_completion_tokens and only the default temperature.
        for _ in range(3):
            try:
                body = await post_json(url, headers, payload, timeout=45.0)
                break
            except ProviderError as exc:
                adjusted = adjust_for_model(payload, exc)
                if adjusted is None:
                    raise
                payload = adjusted
        else:
            body = await post_json(url, headers, payload, timeout=45.0)
        try:
            content = body["choices"][0]["message"].get("content", "")
        except (KeyError, IndexError, TypeError, AttributeError):
            content = ""
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        candidates = parse_items(parsed.get("items"), catalog)
        return VisionResult(
            provider=self.name,
            model=self.model,
            candidates=candidates,
            raw_response=body,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=None,
        )
