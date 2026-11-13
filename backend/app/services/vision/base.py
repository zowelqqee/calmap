"""Provider-agnostic contract for photo recognition.

Two rules encoded here, both from the cost/accuracy analysis:

1. The model returns *catalogue identifiers and grams*, never kcal. Nutrition is
   computed from our own product table, so numbers stay reproducible and a catalogue
   correction retroactively improves past estimates instead of leaving them frozen.
2. Every provider reports latency and estimated cost, because vision spend is the line
   item that decides whether the subscription price works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CatalogHint:
    """The closed vocabulary the model is allowed to answer with."""

    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class RawCandidate:
    slug: str
    grams: float
    confidence: float
    alternatives: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VisionResult:
    provider: str
    model: str
    candidates: list[RawCandidate]
    raw_response: dict
    latency_ms: int | None = None
    cost_usd: float | None = None


class VisionProvider(Protocol):
    name: str
    model: str

    async def recognize(
        self, image: bytes, mime_type: str, catalog: list[CatalogHint]
    ) -> VisionResult: ...


PROMPT_RU = """Ты — ассистент по учёту питания. На фото — приём пищи.

Определи, какие продукты присутствуют, и оцени массу каждого в граммах.

Правила:
- Отвечай ТОЛЬКО продуктами из предоставленного списка (поле slug).
- Не считай калории и БЖУ — только slug и граммы.
- Для каждого продукта укажи confidence от 0 до 1 — насколько ты уверен.
- Если сомневаешься между вариантами, укажи до трёх альтернативных slug.
- Оценка массы важнее точного названия: лучше грубая, но честная оценка.
- Если на фото нет еды, верни пустой список.

Верни строгий JSON:
{"items": [{"slug": "...", "grams": 0, "confidence": 0.0, "alternatives": ["..."]}]}

Доступные продукты:
"""


def build_prompt(catalog: list[CatalogHint]) -> str:
    lines = "\n".join(f"- {c.slug}: {c.name}" for c in catalog)
    return PROMPT_RU + lines


#: An estimate above this is a model error, not a portion.
MAX_GRAMS = 3000.0


def parse_items(items: object, catalog: list[CatalogHint]) -> list[RawCandidate]:
    """Validated candidates from the model's "items": unknown slugs, malformed
    entries and absurd weights are dropped or clamped, never raised."""
    if not isinstance(items, list):
        return []
    known = {c.slug for c in catalog}
    candidates: list[RawCandidate] = []
    for item in items:
        if not isinstance(item, dict) or item.get("slug") not in known:
            continue
        try:
            grams = min(MAX_GRAMS, max(1.0, float(item.get("grams", 0))))
            confidence = min(1.0, max(0.0, float(item.get("confidence", 0.5))))
        except (TypeError, ValueError):
            continue
        if grams != grams or confidence != confidence:  # NaN
            continue
        alternatives = item.get("alternatives")
        candidates.append(
            RawCandidate(
                slug=item["slug"],
                grams=grams,
                confidence=confidence,
                alternatives=[
                    a for a in alternatives if isinstance(a, str) and a in known
                ][:3]
                if isinstance(alternatives, list)
                else [],
            )
        )
    return candidates
