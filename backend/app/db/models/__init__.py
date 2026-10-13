"""Importing this package registers every model on `Base.metadata`.

Alembic's autogenerate and `Base.metadata.create_all` both depend on that, so keep the
re-exports exhaustive.
"""

from app.db.models.assistant import AssistantConversation, AssistantMessage
from app.db.models.billing import (
    TIER_LIMITS,
    TIER_PRICES_RUB,
    BillingEvent,
    Payment,
    Subscription,
)
from app.db.models.catalog import FavoriteRecipe, Product, ProductPrice, Recipe, RecipeItem
from app.db.models.diary import DiaryEntry, VisionRecognition
from app.db.models.plan import MealPlan, MealPlanDay, MealPlanItem
from app.db.models.user import (
    OAuthIdentity,
    OnboardingDraft,
    User,
    UserProfile,
    UserTargets,
)
from app.db.models.wellness import ProgressEntry, Workout, WorkoutExercise

__all__ = [
    "TIER_LIMITS",
    "TIER_PRICES_RUB",
    "AssistantConversation",
    "AssistantMessage",
    "BillingEvent",
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
    "Payment",
    "Subscription",
    "User",
    "UserProfile",
    "UserTargets",
    "VisionRecognition",
    "Workout",
    "WorkoutExercise",
]
