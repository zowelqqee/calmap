"""OpenAI-compatible vision adapter.

Works with OpenAI, an egress gateway, or a compatible local/provider endpoint. The
closed-catalogue prompt and post-validation are shared with Gemini, so changing the
provider cannot cause the model to become the source of nutrition numbers.
"""

from __future__ import annotations

import base64
import json
import time

import httpx

from app.core.config import settings
from app.services.vision.base import CatalogHint, RawCandidate, VisionResult, build_prompt


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
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": build_prompt(catalog)},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Распознай продукты на этом фото и верни JSON."},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64.b64encode(image).decode()}"}},
                    ],
                },
            ],
        }
        started = time.perf_counter()
        client_options = {"timeout": 45.0}
        if settings.openai_proxy_url:
            client_options.update(proxy=settings.openai_proxy_url, trust_env=False)
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.post(
                f"{settings.vision_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.vision_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
        known = {c.slug for c in catalog}
        candidates = []
        for item in parsed.get("items", []):
            if item.get("slug") not in known:
                continue
            candidates.append(
                RawCandidate(
                    slug=item["slug"],
                    grams=max(1.0, float(item.get("grams", 0))),
                    confidence=min(1.0, max(0.0, float(item.get("confidence", 0.5)))),
                    alternatives=[a for a in item.get("alternatives", []) if a in known][:3],
                )
            )
        return VisionResult(
            provider=self.name,
            model=self.model,
            candidates=candidates,
            raw_response=body,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=None,
        )
