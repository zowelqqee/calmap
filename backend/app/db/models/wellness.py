from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class Workout(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "workouts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=35)
    estimated_kcal: Mapped[int] = mapped_column(Integer, nullable=False, default=220)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exercises: Mapped[list[WorkoutExercise]] = relationship(
        back_populates="workout",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="WorkoutExercise.position",
    )

    __table_args__ = (UniqueConstraint("user_id", "day", name="workout_user_day"),)


class WorkoutExercise(Base, UUIDPrimaryKey):
    __tablename__ = "workout_exercises"

    workout_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("workouts.id", ondelete="CASCADE"), index=True
    )
    catalog_id: Mapped[str | None] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sets: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    reps: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    workout: Mapped[Workout] = relationship(back_populates="exercises")


class ProgressEntry(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "progress_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    waist_cm: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("user_id", "day", name="progress_user_day"),)
