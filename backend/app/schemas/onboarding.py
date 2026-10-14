"""Request models for the onboarding questionnaire.

Each step is a separate PATCH so the client can save as the user goes; the server keeps
a draft and only materialises a profile on /complete. Validation lives here rather than
in the client so a stale app build can never write an impossible profile.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator, field_validator

from app.domain import allergens
from app.domain.enums import ActivityLevel, BudgetType, DietType, Goal, Sex, WorkoutLocation


MIN_AGE = 18


class PersonalStep(BaseModel):
    """Step 1 — personal data."""

    sex: Sex
    birth_date: date | None = None
    age: int | None = Field(default=None, ge=MIN_AGE, le=99)
    height_cm: float = Field(ge=100, le=250)
    weight_kg: float = Field(ge=30, le=300)

    @model_validator(mode="after")
    def check_age(self) -> PersonalStep:
        if self.birth_date is None and self.age is None:
            raise ValueError("provide age or birth_date")
        age = self.age
        if age is None and self.birth_date is not None:
            age = int((date.today() - self.birth_date).days / 365.25)
        # Adults only: health data and paid subscriptions of minors would need the
        # consent of a legal representative (152-FZ art. 9, Civil Code art. 26, 28).
        if age is None or not MIN_AGE <= age <= 99:
            raise ValueError(f"age must be between {MIN_AGE} and 99")
        return self

    def resolved_birth_date(self) -> date:
        if self.birth_date is not None:
            return self.birth_date
        today = date.today()
        try:
            return today.replace(year=today.year - int(self.age or 0))
        except ValueError:  # 29 February in a non-leap target year
            return today.replace(year=today.year - int(self.age or 0), day=28)


class GoalStep(BaseModel):
    """Step 2 — goal with an explicit deficit/surplus coefficient."""

    goal: Goal
    #: Fraction of TDEE, e.g. 0.18 for a mild cut. Ignored when goal is `maintain`.
    rate_pct: float | None = Field(default=None, ge=0.0, le=0.5)
    target_weight_kg: float | None = Field(default=None, ge=35, le=300)


class RestrictionsStep(BaseModel):
    """Step 3 — allergies and intolerances."""

    diet: DietType = DietType.OMNIVORE
    allergens: list[str] = Field(default_factory=list)
    excluded_product_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("allergens")
    @classmethod
    def normalise_allergens(cls, values: list[str]) -> list[str]:
        return allergens.normalise(values)


class BudgetStep(BaseModel):
    """Step 4 — food budget."""

    budget_type: BudgetType
    amount: float | None = Field(default=None, gt=0)
    currency: Literal["RUB"] = "RUB"

    @model_validator(mode="after")
    def amount_required_unless_unlimited(self) -> BudgetStep:
        if self.budget_type is not BudgetType.UNLIMITED and self.amount is None:
            raise ValueError("amount is required unless budget_type is 'unlimited'")
        return self


class ActivityStep(BaseModel):
    """Step 5 — activity level (coefficients 1.2 / 1.55 / 1.9)."""

    activity_level: ActivityLevel


class WorkoutLocationStep(BaseModel):
    """Step 6 — where the user will train."""

    location: WorkoutLocation


class OnboardingSessionOut(BaseModel):
    current_step: int
    completed_steps: list[int]
    payload: dict


class TargetsOut(BaseModel):
    bmr_kcal: int
    tdee_kcal: int
    target_kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int
    fiber_g: int
    water_ml: int
    #: Non-empty when a safety rule overrode what the user asked for; show it in the UI.
    adjustments: list[str] = Field(default_factory=list)


class CompleteOut(BaseModel):
    """Payload for the "calculating your plan" screen."""

    targets: TargetsOut
    plan_id: uuid.UUID | None
    activity_coefficient: float
