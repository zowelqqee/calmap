from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
import math
import re
from typing import Any

import httpx

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class RetailOffer:
    slug: str
    name: str
    retailer: str
    available: bool | None
    price: float | None
    currency: str
    price_type: str
    url: str | None = None
    package_size_g: int | None = None
    observed_at: str | None = None


class StubRetailProvider:
    name = "curated_estimate"

    async def offers(self, entries: list[dict], region_code: str, currency: str) -> list[RetailOffer]:
        """Return clearly-labelled basket estimates for common Russian chains.

        These figures are calculated from the local catalogue, so they must never
        be presented as a stock check or a live price.  The shape deliberately
        matches a partner aggregator response: swapping to `HttpRetailProvider`
        later leaves the mobile presentation untouched.
        """
        retailers = (
            ("Пятёрочка", 0.94),
            ("Лента", 0.98),
            ("Перекрёсток", 1.04),
        )
        offers = []
        for retailer, multiplier in retailers:
            for entry in entries:
                price = entry.get("estimated_cost")
                offers.append(
                    RetailOffer(
                        slug=entry["slug"],
                        name=entry.get("name") or entry["slug"].replace("_", " "),
                        retailer=retailer,
                        available=None,
                        price=round(float(price) * multiplier, 2) if price is not None else None,
                        currency=currency,
                        price_type="estimate",
                    )
                )
        return offers


class HttpRetailProvider:
    name = "retail_api"

    async def offers(self, entries: list[dict], region_code: str, currency: str) -> list[RetailOffer]:
        if not settings.retail_base_url or not settings.retail_api_key:
            raise RuntimeError("RETAIL_BASE_URL and RETAIL_API_KEY are required")
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{settings.retail_base_url.rstrip('/')}/offers",
                headers={"Authorization": f"Bearer {settings.retail_api_key}"},
                json={"region_code": region_code, "currency": currency, "items": entries},
            )
            response.raise_for_status()
            body = response.json()
        entries_by_slug = {entry["slug"]: entry for entry in entries}
        offers = []
        for item in body.get("offers", []):
            slug = item["slug"]
            source_entry = entries_by_slug.get(slug, {})
            offers.append(
                RetailOffer(
                    slug=slug,
                    name=item.get("name") or source_entry.get("name") or slug.replace("_", " "),
                    retailer=item["retailer"],
                    available=item.get("available"),
                    price=item.get("price"),
                    currency=item.get("currency", currency),
                    price_type="retailer",
                    url=item.get("url"),
                    package_size_g=item.get("package_size_g"),
                    observed_at=item.get("observed_at"),
                )
            )
        return offers


class ParseBotRetailProvider:
    """Read public Pyaterochka catalogue data through a maintained API adapter.

    Retailer storefronts actively challenge unattended server requests. This
    adapter is intentionally *not* a CAPTCHA/anti-bot bypass: it calls an API
    product that is operated for this purpose, with a key supplied by the app
    operator. A configured store ID scopes the result to that selected store;
    without it, a match only proves presence in the online catalogue.
    """

    name = "parse_bot"
    retailer = "Пятёрочка"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        scraper_id: str | None = None,
        store_id: str | None = None,
        base_url: str = "https://api.parse.bot",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.retail_parse_api_key
        self.scraper_id = (
            scraper_id
            if scraper_id is not None
            else settings.retail_parse_5ka_scraper_id
        )
        self.store_id = (
            store_id if store_id is not None else settings.retail_parse_5ka_store_id
        )
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def offers(
        self, entries: list[dict], region_code: str, currency: str
    ) -> list[RetailOffer]:
        if not self.api_key or not self.scraper_id or not self.store_id:
            raise RuntimeError(
                "RETAIL_PARSE_API_KEY, RETAIL_PARSE_5KA_SCRAPER_ID and "
                "RETAIL_PARSE_5KA_STORE_ID are required for store availability"
            )

        semaphore = asyncio.Semaphore(4)
        async with httpx.AsyncClient(
            timeout=8.0, transport=self.transport, follow_redirects=True
        ) as client:
            results = await asyncio.gather(
                *(self._lookup(client, semaphore, entry, currency) for entry in entries),
                return_exceptions=True,
            )

        offers: list[RetailOffer] = []
        failures = 0
        for result in results:
            if isinstance(result, Exception):
                failures += 1
                continue
            offers.append(result)
        if failures == len(entries) and entries:
            raise RuntimeError("Pyaterochka catalogue is temporarily unavailable")
        return offers

    async def _lookup(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        entry: dict,
        currency: str,
    ) -> RetailOffer:
        params: dict[str, Any] = {
            "query": entry.get("name") or entry["slug"].replace("_", " "),
            "limit": 8,
        }
        if self.store_id:
            params["store_id"] = self.store_id
        async with semaphore:
            response = await client.get(
                f"{self.base_url}/scraper/{self.scraper_id}/get_products",
                headers={"X-API-Key": self.api_key},
                params=params,
            )
        response.raise_for_status()
        product = _best_product_match(entry, response.json())
        now = datetime.now(UTC).isoformat()
        if product is None:
            # A successful search with no candidate is a genuine negative result.
            return RetailOffer(
                slug=entry["slug"],
                name=entry.get("name") or entry["slug"].replace("_", " "),
                retailer=self.retailer,
                available=False,
                price=None,
                currency=currency,
                price_type="retailer",
                observed_at=now,
            )
        package_size_g = _package_size_g(product)
        unit_price = _first_number(product, "price_promo", "price", "price_regular")
        return RetailOffer(
            slug=entry["slug"],
            name=product.get("name") or entry.get("name") or entry["slug"],
            retailer=self.retailer,
            available=True,
            price=_basket_line_price(entry, unit_price, package_size_g),
            currency=currency,
            price_type="retailer",
            url=_product_url(product),
            package_size_g=package_size_g,
            observed_at=now,
        )


class HybridParseBotRetailProvider:
    """Use live 5ka matches while preserving usable estimates for the full basket."""

    name = "parse_bot_with_estimates"

    async def offers(
        self, entries: list[dict], region_code: str, currency: str
    ) -> list[RetailOffer]:
        estimates = await StubRetailProvider().offers(entries, region_code, currency)
        try:
            live = await ParseBotRetailProvider().offers(entries, region_code, currency)
        except (RuntimeError, httpx.HTTPError):
            # A protected/unavailable upstream must never turn into a false "out of
            # stock" claim or hide the remaining comparison from the user.
            return estimates
        live_by_slug = {offer.slug: offer for offer in live}
        return [
            live_by_slug.get(offer.slug, offer)
            if offer.retailer == ParseBotRetailProvider.retailer
            else offer
            for offer in estimates
        ]


def _tokens(value: str) -> set[str]:
    return {
        # Search catalogues inflect Russian names differently: "куриная" vs
        # "куриное", "грудка" vs "грудки". A short stem avoids those false
        # negatives while the multi-token threshold below still rejects a
        # materially different product.
        token[:5]
        for token in re.sub(r"[^a-zа-яё0-9]+", " ", value.lower()).replace("ё", "е").split()
        if len(token) > 1
    }


def _best_product_match(entry: dict, body: Any) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return None
    raw_products = body.get("results") or body.get("products") or body.get("items") or []
    if not isinstance(raw_products, list):
        return None
    target = _tokens(entry.get("name") or entry["slug"].replace("_", " "))
    ranked: list[tuple[float, dict[str, Any]]] = []
    for product in raw_products:
        if not isinstance(product, dict) or not isinstance(product.get("name"), str):
            continue
        candidate = _tokens(product["name"])
        if not candidate:
            continue
        score = len(target & candidate) / len(target | candidate) if target else 0.0
        ranked.append((score, product))
    if not ranked:
        return None
    score, product = max(ranked, key=lambda item: item[0])
    # Avoid substituting a similarly named but materially different food item.
    return product if score >= 0.34 else None


def _first_number(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", ".").replace(" ", ""))
            except ValueError:
                continue
    return None


def _package_size_g(source: dict[str, Any]) -> int | None:
    for key in ("package_size_g", "weight_g", "weight"):
        value = _first_number(source, key)
        if value is not None:
            return round(value)
    return None


def _basket_line_price(
    entry: dict[str, Any], unit_price: float | None, package_size_g: int | None
) -> float | None:
    """Convert a package price into the cost of the planned ingredient amount."""
    if unit_price is None:
        return None
    grams = entry.get("grams")
    if isinstance(grams, (int, float)) and package_size_g and package_size_g > 0:
        return round(math.ceil(float(grams) / package_size_g) * unit_price, 2)
    return unit_price


def _product_url(source: dict[str, Any]) -> str | None:
    for key in ("url", "product_url", "link"):
        value = source.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


@lru_cache
def get_retail_provider():
    if settings.retail_provider == "http":
        return HttpRetailProvider()
    if settings.retail_provider == "parse_bot":
        return HybridParseBotRetailProvider()
    return StubRetailProvider()
