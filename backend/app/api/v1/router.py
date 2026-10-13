from fastapi import APIRouter

from app.api.v1 import assistant, auth, billing, catalog, diary, exercises, meal_plans, me, onboarding, progress, vision, workouts

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(billing.router)
api_router.include_router(assistant.router)
api_router.include_router(onboarding.router)
api_router.include_router(me.router)
api_router.include_router(catalog.router)
api_router.include_router(exercises.router)
api_router.include_router(meal_plans.router)
api_router.include_router(diary.router)
api_router.include_router(vision.router)
api_router.include_router(workouts.router)
api_router.include_router(progress.router)
