import json

import httpx
import pytest

from app.services.retail import ParseBotRetailProvider


def _transport_for(body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "test-key"
        assert request.url.params["query"] == "Куриная грудка, филе"
        assert request.url.params["store_id"] == "MOW-42"
        return httpx.Response(200, content=json.dumps(body))

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_parse_bot_provider_returns_matched_store_product():
    provider = ParseBotRetailProvider(
        api_key="test-key",
        scraper_id="scraper-id",
        store_id="MOW-42",
        base_url="https://retail.example",
        transport=_transport_for(
            {
                "results": [
                    {
                        "name": "Филе грудки куриное охлаждённое",
                        "price": "389.90",
                        "weight_g": 900,
                        "url": "https://5ka.ru/product/chicken",
                    }
                ]
            }
        ),
    )

    offers = await provider.offers(
        [
            {
                "slug": "chicken-breast",
                "name": "Куриная грудка, филе",
                "grams": 1260,
            }
        ],
        "RU-MOW",
        "RUB",
    )

    assert len(offers) == 1
    offer = offers[0]
    assert offer.available is True
    assert offer.price == 779.8
    assert offer.package_size_g == 900
    assert offer.url == "https://5ka.ru/product/chicken"
    assert offer.observed_at


@pytest.mark.asyncio
async def test_parse_bot_provider_marks_absent_only_after_successful_empty_search():
    provider = ParseBotRetailProvider(
        api_key="test-key",
        scraper_id="scraper-id",
        store_id="MOW-42",
        base_url="https://retail.example",
        transport=_transport_for({"results": []}),
    )

    offer = (
        await provider.offers(
            [{"slug": "chicken-breast", "name": "Куриная грудка, филе"}],
            "RU-MOW",
            "RUB",
        )
    )[0]

    assert offer.available is False
    assert offer.price is None
