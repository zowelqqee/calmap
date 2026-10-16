"""Provider-agnostic nutrition assistant.

The assistant may explain and coach, but it is not allowed to calculate targets or
rewrite diary numbers. Those facts are injected from the database and the deterministic
planner remains the source of truth.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class AssistantReply:
    provider: str
    model: str
    content: str
    raw_payload: dict
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AssistantProvider(Protocol):
    name: str
    model: str

    async def reply(self, messages: list[dict[str, str]]) -> AssistantReply: ...


SYSTEM_PROMPT = """Ты — доброжелательный консультант приложения calmap по здоровому питанию.
Отвечай по-русски, кратко и конкретно, учитывая переданный профиль и дневник.
Не ставь диагнозы, не назначай лекарства и не обещай медицинский результат.
Не предлагай опасные голодовки, экстремальный дефицит или отмену лечения.
Калории, БЖУ и цены в контексте — факты из приложения: не пересчитывай их на глаз,
а ссылайся на план и советуй пользователю изменить цель через приложение.
Если вопрос медицинский или связан с расстройством пищевого поведения, посоветуй
обратиться к врачу/диетологу.
"""


class StubAssistantProvider:
    name = "stub"
    model = "stub-v1"

    async def reply(self, messages: list[dict[str, str]]) -> AssistantReply:
        if settings.env == "production":
            raise RuntimeError("stub assistant provider is disabled in production")
        text = messages[-1]["content"] if messages else ""
        return AssistantReply(
            provider=self.name,
            model=self.model,
            content=(
                "Я вижу ваш вопрос. Для точной рекомендации используйте текущий план и "
                "дневник; при медицинских симптомах обратитесь к специалисту. "
                f"Ваш запрос: «{text[:300]}»"
            ),
            raw_payload={"stub": True},
        )


class OpenAICompatibleAssistantProvider:
    name = "openai_compatible"

    def __init__(self) -> None:
        self.model = settings.assistant_model

    async def reply(self, messages: list[dict[str, str]]) -> AssistantReply:
        if not settings.assistant_api_key or not settings.assistant_base_url:
            raise RuntimeError("ASSISTANT_API_KEY and ASSISTANT_BASE_URL are required")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 700,
        }
        started = time.perf_counter()
        try:
            client_options = {"timeout": 45.0}
            if settings.openai_proxy_url:
                client_options.update(proxy=settings.openai_proxy_url, trust_env=False)
            async with httpx.AsyncClient(**client_options) as client:
                response = await client.post(
                    f"{settings.assistant_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.assistant_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError("assistant provider is unavailable") from exc
        choices = body.get("choices") or []
        if not choices or not choices[0].get("message", {}).get("content"):
            raise RuntimeError("assistant provider returned no message")
        usage = body.get("usage") or {}
        return AssistantReply(
            provider=self.name,
            model=self.model,
            content=str(choices[0]["message"]["content"]),
            raw_payload={"latency_ms": int((time.perf_counter() - started) * 1000), "response": body},
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


@lru_cache
def get_assistant_provider() -> AssistantProvider:
    if settings.assistant_provider == "openai_compatible":
        return OpenAICompatibleAssistantProvider()
    return StubAssistantProvider()
