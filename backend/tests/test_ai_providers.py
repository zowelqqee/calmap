"""AI provider calls: retries, model parameter fallback, defensive parsing."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.services import llm_http
from app.services.assistant import OpenAICompatibleAssistantProvider
from app.services.llm_http import ProviderError
from app.services.vision.base import CatalogHint, parse_items
from app.services.vision.openai_compatible import OpenAICompatibleVisionProvider

CATALOG = [CatalogHint("rice", "Рис"), CatalogHint("chicken", "Курица")]


@pytest.fixture
def provider_http(monkeypatch):
    """Scripted provider: a list of (status, body) answers, requests recorded."""
    answers: list[tuple[int, object]] = []
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        status, body = answers.pop(0)
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(llm_http, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(llm_http, "RETRY_DELAY", 0)
    for name, value in {
        "assistant_api_key": "k", "assistant_base_url": "https://llm.test/v1",
        "vision_api_key": "k", "vision_base_url": "https://llm.test/v1",
    }.items():
        monkeypatch.setattr(settings, name, value)
    return answers, requests


def chat(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 5}}


async def test_transient_error_is_retried_once(provider_http):
    answers, requests = provider_http
    answers += [(503, {"error": {"message": "overloaded"}}), (200, chat("Ответ"))]
    reply = await OpenAICompatibleAssistantProvider().reply([{"role": "user", "content": "?"}])
    assert reply.content == "Ответ" and len(requests) == 2


async def test_permanent_errors_are_not_retried_and_name_the_cause(provider_http):
    answers, requests = provider_http
    answers += [(429, {"error": {"code": "insufficient_quota", "message": "no money"}})]
    with pytest.raises(ProviderError) as caught:
        await OpenAICompatibleAssistantProvider().reply([{"role": "user", "content": "?"}])
    assert len(requests) == 1
    assert "insufficient_quota" in str(caught.value) and "k" not in str(caught.value).split()


async def test_newer_models_get_max_completion_tokens(provider_http):
    answers, requests = provider_http
    answers += [
        (400, {"error": {"param": "max_tokens", "message": "Use 'max_completion_tokens'"}}),
        (400, {"error": {"param": "temperature", "message": "temperature is not supported"}}),
    ]
    with pytest.raises(ProviderError):
        await OpenAICompatibleAssistantProvider().reply([{"role": "user", "content": "?"}])
    assert "max_tokens" in requests[0] and "max_completion_tokens" in requests[1]

    requests.clear()
    answers += [
        (400, {"error": {"param": "max_tokens", "message": "unsupported, use max_completion_tokens; temperature unsupported"}}),
        (200, chat("ok")),
    ]
    reply = await OpenAICompatibleAssistantProvider().reply([{"role": "user", "content": "?"}])
    assert reply.content == "ok"
    assert "temperature" not in requests[1] and requests[1]["max_completion_tokens"] == 700


async def test_non_json_answer_is_a_provider_error_not_a_crash(provider_http):
    answers, _ = provider_http
    answers += [(200, "<html>proxy login</html>")]
    with pytest.raises(ProviderError):
        await OpenAICompatibleAssistantProvider().reply([{"role": "user", "content": "?"}])


async def test_vision_survives_malformed_model_output(provider_http):
    answers, requests = provider_http
    content = json.dumps({"items": [
        {"slug": "rice", "grams": 99999, "confidence": 2, "alternatives": 5},
        {"slug": "chicken", "grams": "много"},
        {"slug": "unknown", "grams": 100},
        "garbage",
        {"slug": "chicken", "grams": 150, "confidence": 0.7, "alternatives": ["rice", 1, "x"]},
    ]})
    answers += [(200, chat(content))]
    result = await OpenAICompatibleVisionProvider().recognize(b"img", "image/jpeg", CATALOG)
    assert [(c.slug, c.grams, c.confidence) for c in result.candidates] == [
        ("rice", 3000.0, 1.0), ("chicken", 150.0, 0.7),
    ]
    assert result.candidates[0].alternatives == [] and result.candidates[1].alternatives == ["rice"]
    assert requests[0]["messages"][1]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )


def test_items_that_are_not_a_list_give_no_candidates():
    for items in (None, 5, "rice", {"slug": "rice"}):
        assert parse_items(items, CATALOG) == []
