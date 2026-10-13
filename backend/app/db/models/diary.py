from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.db.models.user import enum_column
from app.domain.enums import MealType


class DiaryEntry(Base, UUIDPrimaryKey, Timestamped):
    """One logged food item.

    Nutrients are copied in at log time rather than joined at read time: catalogue
    corrections must not silently rewrite what a user ate three weeks ago.
    """

    __tablename__ = "diary_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    meal_type: Mapped[MealType] = enum_column(MealType, nullable=False)

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL")
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recipes.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    grams: Mapped[float] = mapped_column(Float, nullable=False)

    kcal: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, nullable=False)

    #: manual | search | barcode | vision | plan | repeat — drives the funnel metrics
    #: that tell us whether photo logging is actually being used.
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)


class VisionRecognition(Base, UUIDPrimaryKey, Timestamped):
    """A photo-recognition attempt and what the user did with it.

    `raw_response` plus `confirmed_items` is the training/eval set for improving
    accuracy: the delta between the two is the only ground truth we will ever get.
    """

    __tablename__ = "vision_recognitions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    image_key: Mapped[str | None] = mapped_column(String(512))
    image_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column()
    cost_usd: Mapped[float | None] = mapped_column(Float)

    raw_response: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: What the model proposed, normalised to catalogue products.
    candidates: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    #: What the user actually confirmed, after editing.
    confirmed_items: Mapped[list[dict] | None] = mapped_column(JSONB)
    was_edited: Mapped[bool | None] = mapped_column()
