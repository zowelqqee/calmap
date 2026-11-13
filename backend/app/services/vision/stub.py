"""Deterministic offline provider.

Lets the whole photo-logging flow — upload, confirmation screen, diary write, edit
metrics — be developed and tested without an API key, an egress proxy, or a cent of
spend. The output shape is identical to the real provider's.
"""

from __future__ import annotations

import hashlib

from app.core.config import settings
from app.services.vision.base import CatalogHint, RawCandidate, VisionResult


class StubVisionProvider:
    name = "stub"
    model = "stub-v1"

    async def recognize(
        self, image: bytes, mime_type: str, catalog: list[CatalogHint]
    ) -> VisionResult:
        if settings.env == "production":
            # Random products presented as a recognition result would mislead users.
            raise RuntimeError("stub vision provider is disabled in production")
        if not catalog:
            return VisionResult(
                provider=self.name, model=self.model, candidates=[], raw_response={}, latency_ms=0
            )

        # Derive a stable pseudo-random pick from the image bytes so the same photo
        # always yields the same answer — required for cache and dedup tests.
        digest = hashlib.sha256(image).digest()
        count = 2 + digest[0] % 2
        candidates: list[RawCandidate] = []
        for i in range(count):
            index = int.from_bytes(digest[i * 4 : i * 4 + 4], "big") % len(catalog)
            grams = 60 + (digest[8 + i] % 24) * 10  # 60..290 g in 10 g steps
            confidence = 0.55 + (digest[16 + i] % 40) / 100.0
            alternatives = [
                catalog[(index + offset) % len(catalog)].slug for offset in (1, 2)
            ]
            candidates.append(
                RawCandidate(
                    slug=catalog[index].slug,
                    grams=float(grams),
                    confidence=round(confidence, 2),
                    alternatives=alternatives,
                )
            )

        return VisionResult(
            provider=self.name,
            model=self.model,
            candidates=candidates,
            raw_response={"stub": True, "image_bytes": len(image), "mime_type": mime_type},
            latency_ms=1,
            cost_usd=0.0,
        )
