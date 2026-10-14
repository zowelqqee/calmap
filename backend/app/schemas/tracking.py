from __future__ import annotations

import uuid
from typing import Literal
from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import MealType


# ----------------------------------------------------------------------- catalogue


class ProductOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    category: str
    barcode: str | None
    kcal_per_100g: float
    protein_per_100g: float
    fat_per_100g: float
    carbs_per_100g: float
    allergens: list[str]
    price_per_kg: float | None = None


class RecipeOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    meal_types: list[str]
    kcal_per_100g: float
    protein_per_100g: float
    fat_per_100g: float
    carbs_per_100g: float
    base_grams: float
    prep_minutes: int
    description: str | None = None
    image_url: str | None = None
    difficulty: str = "easy"
    tags: list[str]
    allergens: list[str]


class RecipeIngredientOut(BaseModel):
    slug: str
    name: str
    grams: float
    estimated_cost: float | None
    store: str = "Средняя цена по Москве"


class RecipeDetailOut(RecipeOut):
    instructions: list[str]
    ingredients: list[RecipeIngredientOut]
    estimated_cost: float
    currency: str = "RUB"
    price_notice: str = "Цены примерные и могут отличаться от фактических."
    is_favorite: bool = False


# --------------------------------------------------------------------------- diary


class DiaryEntryCreate(BaseModel):
    day: date
    meal_type: MealType
    grams: float = Field(default=1, gt=0, le=5000)
    product_id: uuid.UUID | None = None
    recipe_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kcal: float | None = Field(default=None, gt=0, le=100000)
    protein_g: float = Field(default=0, ge=0, le=10000)
    fat_g: float = Field(default=0, ge=0, le=10000)
    carbs_g: float = Field(default=0, ge=0, le=10000)
    # "vision" and "repeat" are written only by their own endpoints, never by clients.
    source: Literal["manual", "search", "plan", "barcode"] = "manual"

    @model_validator(mode="after")
    def exactly_one_reference(self) -> DiaryEntryCreate:
        references = [self.product_id, self.recipe_id]
        if sum(reference is not None for reference in references) > 1:
            raise ValueError("provide only one of product_id or recipe_id")
        if self.product_id is None and self.recipe_id is None:
            if self.name is None or self.kcal is None:
                raise ValueError("custom entries require name and kcal")
        return self


class DiaryEntryOut(BaseModel):
    id: uuid.UUID
    day: date
    meal_type: MealType
    name: str
    grams: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    source: str


class DiarySummaryOut(BaseModel):
    day: date
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    target_kcal: int | None
    target_protein_g: int | None
    target_fat_g: int | None
    target_carbs_g: int | None
    entries: list[DiaryEntryOut]


class RepeatMealRequest(BaseModel):
    """"Same as yesterday" — the cheapest possible logging action, and the one that
    keeps vision spend down for regular users."""

    source_day: date
    target_day: date
    meal_type: MealType


# -------------------------------------------------------------------------- vision


class VisionCandidateOut(BaseModel):
    product_id: uuid.UUID | None
    product_slug: str | None
    name: str
    grams_estimate: float
    confidence: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    #: Alternative matches for one-tap correction on the confirmation screen.
    alternatives: list[str] = Field(default_factory=list)


class VisionRecognizeOut(BaseModel):
    recognition_id: uuid.UUID
    provider: str
    model: str
    latency_ms: int | None
    candidates: list[VisionCandidateOut]
    #: Always true: the confirmation screen is mandatory, never a silent auto-log.
    requires_confirmation: bool = True


class VisionConfirmItem(BaseModel):
    product_id: uuid.UUID
    grams: float = Field(gt=0, le=5000)


class VisionConfirmRequest(BaseModel):
    day: date
    meal_type: MealType
    items: list[VisionConfirmItem]
