"""Importing this package registers every model on `Base.metadata`.

Alembic's autogenerate and `Base.metadata.create_all` both depend on that, so keep the
re-exports exhaustive.
"""

from app.db.models.assistant import AssistantConversation, AssistantMessage
from app.db.models.consent import AccountDeletion, UserConsent
from app.db.models.catalog import FavoriteRecipe, Product, ProductPrice, Recipe, RecipeItem
from app.db.models.diary import DiaryEntry, VisionRecognition
from app.db.models.plan import MealPlan, MealPlanDay, MealPlanItem
from app.db.models.subscription import (
    PAID_TIERS,
    TIER_LIMITS,
    PaymentStatus,
    Subscription,
    SubscriptionEvent,
    TelegramLink,
)
from app.db.models.user import (
    AuthSession,
    OAuthIdentity,
    OnboardingDraft,
    PhoneCode,
    User,
    UserProfile,
    UserTargets,
)
from app.db.models.wellness import ProgressEntry, Workout, WorkoutExercise

__all__ = [
    "PAID_TIERS",
    "TIER_LIMITS",
    "AccountDeletion",
    "AssistantConversation",
    "AuthSession",
    "AssistantMessage",
    "DiaryEntry",
    "FavoriteRecipe",
    "MealPlan",
    "MealPlanDay",
    "MealPlanItem",
    "OAuthIdentity",
    "OnboardingDraft",
    "Product",
    "ProductPrice",
    "ProgressEntry",
    "Recipe",
    "RecipeItem",
    "PaymentStatus",
    "PhoneCode",
    "Subscription",
    "SubscriptionEvent",
    "TelegramLink",
    "User",
    "UserConsent",
    "UserProfile",
    "UserTargets",
    "VisionRecognition",
    "Workout",
    "WorkoutExercise",
]
