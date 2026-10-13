from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.db.models.user import enum_column
from app.domain.enums import MealType


class MealPlan(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "meal_plans"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ready", nullable=False)

    target_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_total: Mapped[float | None] = mapped_column(Float)
    cost_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)

    #: Serialised Relaxation objects — what the solver had to give up on and why.
    relaxations: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)

    days: Mapped[list[MealPlanDay]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin", order_by="MealPlanDay.day"
    )


class MealPlanDay(Base, UUIDPrimaryKey):
    __tablename__ = "meal_plan_days"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    kcal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    plan: Mapped[MealPlan] = relationship(back_populates="days")
    items: Mapped[list[MealPlanItem]] = relationship(
        back_populates="day_row", cascade="all, delete-orphan", lazy="selectin"
    )


class MealPlanItem(Base, UUIDPrimaryKey):
    __tablename__ = "meal_plan_items"

    day_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("meal_plan_days.id", ondelete="CASCADE"), index=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recipes.id", ondelete="RESTRICT")
    )
    meal_type: Mapped[MealType] = enum_column(MealType, nullable=False)
    grams: Mapped[float] = mapped_column(Float, nullable=False)
    kcal: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, nullable=False)
    #: Cost is frozen at generation time — prices move, the plan the user saw must not.
    cost: Mapped[float] = mapped_column(Float, nullable=False)

    day_row: Mapped[MealPlanDay] = relationship(back_populates="items")
