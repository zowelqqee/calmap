from fastapi import APIRouter, Depends

from app.api.deps import require_access
from app.api.v1 import (
    assistant,
    auth,
    bot,
    catalog,
    consents,
    diary,
    exercises,
    meal_plans,
    me,
    onboarding,
    progress,
    subscription,
    vision,
    workouts,
)

api_router = APIRouter(prefix="/v1")

# Always available: sign-in and account management, consents, the questionnaire,
# the subscription status itself and the payment bot's own API.
api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(subscription.router)
api_router.include_router(consents.router)
api_router.include_router(bot.router)

# Everything else requires a paid period or the trial.
paid = [Depends(require_access)]
for module in (me, catalog, exercises, meal_plans, diary, vision, workouts, progress, assistant):
    api_router.include_router(module.router, dependencies=paid)
