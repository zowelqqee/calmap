from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel


class RetailOfferOut(BaseModel):
    slug: str
    name: str
    retailer: str
    available: bool | None
    price: float | None
    currency: str
    price_type: Literal["estimate", "retailer"]
    url: str | None = None
    package_size_g: int | None = None
    observed_at: str | None = None


class ShoppingOffersOut(BaseModel):
    plan_id: uuid.UUID
    region_code: str
    offers: list[RetailOfferOut]
