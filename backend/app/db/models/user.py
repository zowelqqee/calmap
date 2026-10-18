from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.domain.enums import ActivityLevel, BudgetType, DietType, Goal, Sex, WorkoutLocation


def enum_column(python_enum: type, **kwargs):
    """VARCHAR-backed enum: avoids Postgres ENUM type churn in migrations."""
    return mapped_column(
        SAEnum(python_enum, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e]),
        **kwargs,
    )


class User(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    #: Russian mobile number confirmed by SMS, normalised to 7XXXXXXXXXX.
    phone: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    password_hash: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    region_code: Mapped[str] = mapped_column(String(16), default="RU-MOW", nullable=False)

    profile: Mapped[UserProfile | None] = relationship(back_populates="user", uselist=False)
    identities: Mapped[list[OAuthIdentity]] = relationship(back_populates="user")


class AuthSession(Base, UUIDPrimaryKey, Timestamped):
    """One signed-in device. Tokens carry its id; revoking it signs the device out.

    The refresh token rotates on every use: only the current one (or, for a short
    grace period, the one before it, in case the answer was lost) is accepted. An
    older one being presented means it was copied, and the session is revoked.
    """

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_jti: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_jti: Mapped[str | None] = mapped_column(String(32))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PhoneCode(Base, UUIDPrimaryKey, Timestamped):
    """One SMS code: sign-in or confirmation of account deletion. Only an HMAC of
    the code is stored."""

    __tablename__ = "phone_codes"

    phone: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: sign_in | delete_account — a code works only for what it was sent for.
    purpose: Mapped[str] = mapped_column(
        String(16), default="sign_in", server_default="sign_in", nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(45))


class OAuthIdentity(Base, UUIDPrimaryKey, Timestamped):
    """Apple / Google / VK sign-in. One row per provider account."""

    __tablename__ = "oauth_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))

    user: Mapped[User] = relationship(back_populates="identities")

    __table_args__ = (UniqueConstraint("provider", "subject", name="provider_subject"),)


class UserProfile(Base, UUIDPrimaryKey, Timestamped):
    """The answers to the onboarding questionnaire, in final form."""

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )

    # step 1 — personal
    sex: Mapped[Sex] = enum_column(Sex, nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    height_cm: Mapped[float] = mapped_column(Float, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)

    # step 2 — goal
    goal: Mapped[Goal] = enum_column(Goal, nullable=False)
    rate_pct: Mapped[float | None] = mapped_column(Float)
    target_weight_kg: Mapped[float | None] = mapped_column(Float)

    # step 3 — restrictions
    diet: Mapped[DietType] = enum_column(DietType, nullable=False, default=DietType.OMNIVORE)
    allergens: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    excluded_product_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # step 4 — budget
    budget_type: Mapped[BudgetType] = enum_column(BudgetType, nullable=False)
    budget_amount: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)

    # steps 5–6 — activity and workout route
    activity_level: Mapped[ActivityLevel] = enum_column(ActivityLevel, nullable=False)
    workout_location: Mapped[WorkoutLocation] = enum_column(
        WorkoutLocation, default=WorkoutLocation.HOME, nullable=False
    )
    workout_equipment: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    workout_focus_muscles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # Programme dates power the progress dashboard. They are created when onboarding
    # completes and may later be edited without rewriting historical measurements.
    program_started_on: Mapped[date | None] = mapped_column(Date)
    program_ends_on: Mapped[date | None] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="profile")

    @property
    def daily_budget(self) -> float | None:
        """Normalise every budget type to roubles per day; None means unlimited."""
        if self.budget_type is BudgetType.UNLIMITED or self.budget_amount is None:
            return None
        if self.budget_type is BudgetType.FIXED_DAY:
            return self.budget_amount
        return self.budget_amount / 7.0  # fixed_week and custom_week


class OnboardingDraft(Base, UUIDPrimaryKey, Timestamped):
    """Partially completed questionnaire.

    Kept server-side and patched step by step so a user who closes the app at step 4
    resumes where they left off instead of starting over — the single biggest drop-off
    point in an onboarding this long.
    """

    __tablename__ = "onboarding_drafts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class UserTargets(Base, UUIDPrimaryKey, Timestamped):
    """Computed plan. Versioned: recomputed on weight/goal change, history retained."""

    __tablename__ = "user_targets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    bmr_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    tdee_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    target_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    protein_g: Mapped[int] = mapped_column(Integer, nullable=False)
    fat_g: Mapped[int] = mapped_column(Integer, nullable=False)
    carbs_g: Mapped[int] = mapped_column(Integer, nullable=False)
    fiber_g: Mapped[int] = mapped_column(Integer, nullable=False)
    water_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    adjustments: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
