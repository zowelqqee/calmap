from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.domain.enums import MealType


class GeneratePlanRequest(BaseModel):
    date_from: date | None = None
    days: int = Field(default=7, ge=1, le=28)
    # Bounded: the solver's work grows with the number of slots.
    meal_slots: list[MealType] | None = Field(default=None, min_length=1, max_length=6)
    exclude_recipe_slugs: list[str] = Field(default_factory=list, max_length=200)


class PlanItemOut(BaseModel):
    id: uuid.UUID
    recipe_slug: str
    recipe_name: str
    meal_type: MealType
    grams: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    cost: float
    image_url: str | None = None
    prep_minutes: int = 0
    difficulty: str = "easy"


class PlanDayOut(BaseModel):
    day: date
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    cost: float
    items: list[PlanItemOut]


class RelaxationOut(BaseModel):
    """Why the plan is not perfect — the answer to "no solution" is never silence."""

    reason: str
    detail: str
    numbers: dict[str, float] = Field(default_factory=dict)
    day_offset: int | None = None


class PlanOut(BaseModel):
    id: uuid.UUID
    date_from: date
    date_to: date
    status: str
    target_kcal: int
    budget_total: float | None
    cost_total: float
    currency: str
    days: list[PlanDayOut]
    relaxations: list[RelaxationOut] = Field(default_factory=list)


class ShoppingListEntry(BaseModel):
    slug: str
    name: str
    category: str
    grams: int
    estimated_cost: float | None
    store: str = "Средняя цена по Москве"


class ShoppingListOut(BaseModel):
    plan_id: uuid.UUID
    currency: str
    total_estimated_cost: float
    entries: list[ShoppingListEntry]
    price_notice: str = "Цены примерные и могут отличаться от фактических."


class PlanCalendarDayOut(BaseModel):
    day: date
    plan_id: uuid.UUID
    has_plan: bool = True
    kcal: float
    cost: float
    has_weight_record: bool = False


class SwapItemRequest(BaseModel):
    """Regenerate a single meal, leaving the rest of the day untouched."""

    item_id: uuid.UUID
