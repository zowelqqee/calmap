"""The onboarding questionnaire.

Progress is stored server-side after every step. That is the whole point: this
onboarding is long (splash → 3 intro screens → sign-up → 6 steps → calculation), and a
client-only draft loses everything when the app is backgrounded during a phone call.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_access
from app.db.models import OnboardingDraft, UserProfile
from app.domain.enums import ActivityLevel, BudgetType, DietType, Goal, Sex, WorkoutLocation
from app.schemas.onboarding import (
    ActivityStep,
    BudgetStep,
    CompleteOut,
    GoalStep,
    OnboardingSessionOut,
    PersonalStep,
    RestrictionsStep,
    TargetsOut,
    WorkoutLocationStep,
)
from app.services.planning import generate_meal_plan, store_targets, targets_for_profile

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

STEP_KEYS = {
    1: "personal",
    2: "goal",
    3: "restrictions",
    4: "budget",
    5: "activity",
    6: "workout_location",
}


async def _draft(session: DbSession, user_id) -> OnboardingDraft:
    draft = await session.scalar(
        select(OnboardingDraft).where(OnboardingDraft.user_id == user_id)
    )
    if draft is None:
        draft = OnboardingDraft(user_id=user_id, current_step=1, payload={})
        session.add(draft)
        await session.flush()
    return draft


def _completed_steps(payload: dict) -> list[int]:
    return sorted(step for step, key in STEP_KEYS.items() if key in payload)


async def _save_step(session: DbSession, user, step: int, data: dict) -> OnboardingSessionOut:
    draft = await _draft(session, user.id)
    payload = dict(draft.payload)
    payload[STEP_KEYS[step]] = data
    draft.payload = payload
    completed = _completed_steps(payload)
    draft.current_step = min(6, max(completed) + 1) if completed else 1
    await session.flush()
    return OnboardingSessionOut(
        current_step=draft.current_step, completed_steps=completed, payload=payload
    )


@router.get("/session", response_model=OnboardingSessionOut)
async def get_session(user: CurrentUser, session: DbSession) -> OnboardingSessionOut:
    draft = await _draft(session, user.id)
    return OnboardingSessionOut(
        current_step=draft.current_step,
        completed_steps=_completed_steps(draft.payload),
        payload=draft.payload,
    )


@router.patch("/personal", response_model=OnboardingSessionOut)
async def step_personal(
    payload: PersonalStep, user: CurrentUser, session: DbSession
) -> OnboardingSessionOut:
    return await _save_step(session, user, 1, payload.model_dump(mode="json"))


@router.patch("/goal", response_model=OnboardingSessionOut)
async def step_goal(
    payload: GoalStep, user: CurrentUser, session: DbSession
) -> OnboardingSessionOut:
    return await _save_step(session, user, 2, payload.model_dump(mode="json"))


@router.patch("/restrictions", response_model=OnboardingSessionOut)
async def step_restrictions(
    payload: RestrictionsStep, user: CurrentUser, session: DbSession
) -> OnboardingSessionOut:
    return await _save_step(session, user, 3, payload.model_dump(mode="json"))


@router.patch("/budget", response_model=OnboardingSessionOut)
async def step_budget(
    payload: BudgetStep, user: CurrentUser, session: DbSession
) -> OnboardingSessionOut:
    return await _save_step(session, user, 4, payload.model_dump(mode="json"))


@router.patch("/activity", response_model=OnboardingSessionOut)
async def step_activity(
    payload: ActivityStep, user: CurrentUser, session: DbSession
) -> OnboardingSessionOut:
    return await _save_step(session, user, 5, payload.model_dump(mode="json"))


@router.patch("/workout-location", response_model=OnboardingSessionOut)
async def step_workout_location(
    payload: WorkoutLocationStep, user: CurrentUser, session: DbSession
) -> OnboardingSessionOut:
    return await _save_step(session, user, 6, payload.model_dump(mode="json"))


@router.post("/complete", response_model=CompleteOut, dependencies=[Depends(require_access)])
async def complete(user: CurrentUser, session: DbSession) -> CompleteOut:
    """Materialise the profile, compute targets and build the first week's plan.

    This backs the "calculating your plan" screen. It runs inline because the whole
    thing takes milliseconds — the solver is local and there is no LLM call on this
    path. Move it to a job queue only if catalogue growth makes that untrue.
    """
    draft = await _draft(session, user.id)
    # Older drafts predate the location branch; keep them resumable and use the
    # safe home route when they are completed by a newer client.
    missing = [
        step for step, key in STEP_KEYS.items()
        if step < 6 and key not in draft.payload
    ]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"onboarding steps not completed: {missing}",
        )

    personal = PersonalStep(**draft.payload["personal"])
    goal = GoalStep(**draft.payload["goal"])
    restrictions = RestrictionsStep(**draft.payload["restrictions"])
    budget = BudgetStep(**draft.payload["budget"])
    activity = ActivityStep(**draft.payload["activity"])
    workout_location = WorkoutLocationStep(
        **draft.payload.get("workout_location", {"location": WorkoutLocation.HOME.value})
    )

    profile = await session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        profile = UserProfile(user_id=user.id)
        session.add(profile)

    profile.sex = Sex(personal.sex)
    profile.birth_date = personal.resolved_birth_date()
    profile.height_cm = personal.height_cm
    profile.weight_kg = personal.weight_kg
    profile.goal = Goal(goal.goal)
    profile.rate_pct = 0.0 if goal.goal is Goal.MAINTAIN else 0.15
    profile.target_weight_kg = goal.target_weight_kg
    profile.diet = DietType(restrictions.diet)
    profile.allergens = restrictions.allergens
    profile.excluded_product_ids = [str(i) for i in restrictions.excluded_product_ids]
    profile.budget_type = BudgetType(budget.budget_type)
    profile.budget_amount = budget.amount
    profile.currency = budget.currency
    profile.activity_level = ActivityLevel(activity.activity_level)
    profile.workout_location = WorkoutLocation(workout_location.location)
    profile.workout_equipment = (
        ["вес тела", "без оборудования"]
        if profile.workout_location is WorkoutLocation.HOME
        else []
    )
    profile.program_started_on = profile.program_started_on or date.today()
    profile.program_ends_on = profile.program_ends_on or date.today() + timedelta(weeks=12)
    await session.flush()

    computed = targets_for_profile(profile)
    targets_row = await store_targets(session, user.id, computed)

    plan = await generate_meal_plan(session, user, profile, targets_row)
    user.onboarding_completed_at = datetime.now(timezone.utc)
    await session.flush()

    return CompleteOut(
        targets=TargetsOut(
            bmr_kcal=computed.bmr_kcal,
            tdee_kcal=computed.tdee_kcal,
            target_kcal=computed.target_kcal,
            protein_g=computed.protein_g,
            fat_g=computed.fat_g,
            carbs_g=computed.carbs_g,
            fiber_g=computed.fiber_g,
            water_ml=computed.water_ml,
            adjustments=list(computed.adjustments),
        ),
        plan_id=plan.id,
        activity_coefficient=profile.activity_level.coefficient,
    )
