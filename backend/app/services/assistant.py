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

from app.core.config import settings
from app.services.llm_http import ProviderError, post_json


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
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 700,
        }
        url = f"{settings.assistant_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {settings.assistant_api_key}"}
        started = time.perf_counter()
        try:
            body = await post_json(url, headers, payload, timeout=45.0)
        except ProviderError as exc:
            adjusted = _adjust_for_model(payload, exc)
            if adjusted is None:
                raise
            # Newer OpenAI models take max_completion_tokens and only the default
            # temperature; older and compatible endpoints take the classic names.
            body = await post_json(url, headers, adjusted, timeout=45.0)
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


def _adjust_for_model(payload: dict, exc: ProviderError) -> dict | None:
    """The same request without the parameters the model refused, or None."""
    if exc.status != 400:
        return None
    error = exc.error
    text = f"{error.get('param') or ''} {error.get('message') or ''}"
    adjusted = dict(payload)
    if "max_tokens" in text and "max_tokens" in adjusted:
        adjusted["max_completion_tokens"] = adjusted.pop("max_tokens")
    if "temperature" in text:
        adjusted.pop("temperature", None)
    return adjusted if adjusted != payload else None


@lru_cache
def get_assistant_provider() -> AssistantProvider:
    if settings.assistant_provider == "openai_compatible":
        return OpenAICompatibleAssistantProvider()
    return StubAssistantProvider()
