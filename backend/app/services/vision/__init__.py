from functools import lru_cache

from app.core.config import settings
from app.services.vision.base import (
    CatalogHint,
    RawCandidate,
    VisionProvider,
    VisionResult,
    build_prompt,
)
from app.services.vision.gemini import GeminiVisionProvider
from app.services.vision.openai_compatible import OpenAICompatibleVisionProvider
from app.services.vision.stub import StubVisionProvider


@lru_cache
def get_vision_provider() -> VisionProvider:
    if settings.vision_provider == "gemini":
        return GeminiVisionProvider()
    if settings.vision_provider == "openai_compatible":
        return OpenAICompatibleVisionProvider()
    return StubVisionProvider()


__all__ = [
    "CatalogHint",
    "GeminiVisionProvider",
    "OpenAICompatibleVisionProvider",
    "RawCandidate",
    "StubVisionProvider",
    "VisionProvider",
    "VisionResult",
    "build_prompt",
    "get_vision_provider",
]
