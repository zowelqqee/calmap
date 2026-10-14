from __future__ import annotations

import logging
import uuid
from datetime import date
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.deps import ActiveAccess, CurrentProfile, CurrentUser, DbSession
from app.db.models import MealPlan, MealPlanDay, MealPlanItem, ProgressEntry, Recipe
from app.domain.allergens import catalogue_exclusions
from app.domain.enums import MealType
from app.domain.solver import DayTargets, MenuRequest, build_day
from app.services.catalog import load_recipe_candidates
from app.schemas.plan import (
    GeneratePlanRequest,
    PlanDayOut,
    PlanItemOut,
    PlanOut,
    PlanCalendarDayOut,
    RelaxationOut,
    ShoppingListEntry,
    ShoppingListOut,
)
from app.schemas.retail import RetailOfferOut, ShoppingOffersOut
from app.services.retail import get_retail_provider
from app.services.planning import current_targets, generate_meal_plan, shopping_list

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/meal-plans", tags=["meal-plans"])


async def _serialize(session: DbSession, plan: MealPlan) -> PlanOut:
    recipes = {
        recipe.id: recipe for recipe in (await session.scalars(select(Recipe))).all()
    }
    day_rows = (
        await session.scalars(
            select(MealPlanDay)
            .where(MealPlanDay.plan_id == plan.id)
            .options(selectinload(MealPlanDay.items))
            .order_by(MealPlanDay.day)
        )
    ).all()
    days = []
    for day_row in day_rows:
        items = []
        for item in day_row.items:
            recipe = recipes.get(item.recipe_id)
            slug = recipe.slug if recipe else "unknown"
            name = recipe.name if recipe else "Неизвестное блюдо"
            items.append(
                PlanItemOut(
                    id=item.id,
                    recipe_slug=slug,
                    recipe_name=name,
                    meal_type=item.meal_type,
                    grams=item.grams,
                    kcal=item.kcal,
                    protein_g=item.protein_g,
                    fat_g=item.fat_g,
                    carbs_g=item.carbs_g,
                    cost=item.cost,
                    image_url=recipe.image_url if recipe else None,
                    prep_minutes=recipe.prep_minutes if recipe else 0,
                    difficulty=recipe.difficulty if recipe else "easy",
                )
            )
        days.append(
            PlanDayOut(
                day=day_row.day,
                kcal=day_row.kcal,
                protein_g=day_row.protein_g,
                fat_g=day_row.fat_g,
                carbs_g=day_row.carbs_g,
                cost=day_row.cost,
                items=items,
            )
        )
    return PlanOut(
        id=plan.id,
        date_from=plan.date_from,
        date_to=plan.date_to,
        status=plan.status,
        target_kcal=plan.target_kcal,
        budget_total=plan.budget_total,
        cost_total=plan.cost_total,
        currency=plan.currency,
        days=days,
        relaxations=[RelaxationOut(**r) for r in plan.relaxations],
    )


async def _owned_plan(session: DbSession, plan_id: uuid.UUID, user_id: uuid.UUID) -> MealPlan:
    plan = await session.get(MealPlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")
    return plan


@router.post("/generate", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def generate(
    payload: GeneratePlanRequest,
    user: CurrentUser,
    profile: CurrentProfile,
    session: DbSession,
    access: ActiveAccess,
) -> PlanOut:
    targets = await current_targets(session, user.id)
    if targets is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "compute targets first")

    days = min(payload.days, access.limits["plan_days"])
    plan = await generate_meal_plan(
        session,
        user,
        profile,
        targets,
        date_from=payload.date_from,
        days=days,
        meal_slots=tuple(payload.meal_slots) if payload.meal_slots else None,
        exclude_recipe_ids=frozenset(payload.exclude_recipe_slugs),
    )
    return await _serialize(session, plan)


@router.get("/current", response_model=PlanOut)
async def current_plan(
    user: CurrentUser,
    session: DbSession,
    access: ActiveAccess,
    day: date | None = None,
) -> PlanOut:
    requested = day or date.today()
    plan = await session.scalar(
        select(MealPlan)
        .where(
            MealPlan.user_id == user.id,
            MealPlan.date_from <= requested,
            MealPlan.date_to >= requested,
        )
        .order_by(MealPlan.created_at.desc())
        .limit(1)
    )
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no plan for this date")
    return await _serialize(session, plan)


@router.get("/calendar", response_model=list[PlanCalendarDayOut])
async def plan_calendar(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    session: DbSession,
    access: ActiveAccess,
) -> list[PlanCalendarDayOut]:
    if (date_to - date_from).days > 62:
        raise HTTPException(422, "range is limited to 63 days")
    rows = (
        await session.execute(
            select(MealPlanDay, MealPlan.id, MealPlan.created_at)
            .join(MealPlan, MealPlan.id == MealPlanDay.plan_id)
            .where(
                MealPlan.user_id == user.id,
                MealPlanDay.day >= date_from,
                MealPlanDay.day <= date_to,
            )
            .order_by(MealPlanDay.day, MealPlan.created_at)
        )
    ).all()
    weight_days = set((await session.scalars(
        select(ProgressEntry.day).where(
            ProgressEntry.user_id == user.id,
            ProgressEntry.day >= date_from,
            ProgressEntry.day <= date_to,
        )
    )).all())
    by_day = {
        row.day: PlanCalendarDayOut(
            day=row.day, plan_id=plan_id, kcal=row.kcal, cost=row.cost,
            has_weight_record=row.day in weight_days,
        )
        for row, plan_id, _created_at in rows
    }
    return [by_day[key] for key in sorted(by_day)]


@router.get("/{plan_id}", response_model=PlanOut)
async def get_plan(
    plan_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    access: ActiveAccess,
) -> PlanOut:
    return await _serialize(session, await _owned_plan(session, plan_id, user.id))


@router.get("/{plan_id}/shopping-list", response_model=ShoppingListOut)
async def get_shopping_list(
    plan_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    access: ActiveAccess,
    day: date | None = None,
) -> ShoppingListOut:
    """Aggregated ingredients with an estimated cost.

    This is the deliberate v1 stand-in for "where to buy": it delivers most of the
    perceived value of retail integration without depending on a retailer API that no
    startup gets on day one.
    """
    plan = await _owned_plan(session, plan_id, user.id)
    entries = await shopping_list(session, plan, user.region_code, day=day)
    return ShoppingListOut(
        plan_id=plan.id,
        currency=plan.currency,
        total_estimated_cost=round(
            sum(e["estimated_cost"] or 0.0 for e in entries), 2
        ),
        entries=[ShoppingListEntry(**e) for e in entries],
    )


@router.get("/{plan_id}/shopping-list/offers", response_model=ShoppingOffersOut)
async def get_shopping_offers(
    plan_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    access: ActiveAccess,
    day: date | None = None,
) -> ShoppingOffersOut:
    """Return retailer offers through a configured partner adapter.

    The default provider returns a clearly labelled catalogue estimate and does not
    claim store availability. Switching `RETAIL_PROVIDER=http` makes the same mobile
    contract call a partner aggregator; those offers carry retailer attribution,
    availability, URL and observation time when supplied by the provider.
    """
    plan = await _owned_plan(session, plan_id, user.id)
    entries = await shopping_list(session, plan, user.region_code, day=day)
    try:
        offers = await get_retail_provider().offers(entries, user.region_code, plan.currency)
    except RuntimeError:
        # The message can name configuration keys; it goes to the log only.
        logger.exception("retail provider failed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "shopping offers are temporarily unavailable"
        ) from None
    return ShoppingOffersOut(
        plan_id=str(plan.id),
        region_code=user.region_code,
        offers=[RetailOfferOut(**asdict(offer)) for offer in offers],
    )


@router.post("/{plan_id}/items/{item_id}/swap", response_model=PlanOut)
async def swap_item(
    plan_id: uuid.UUID,
    item_id: uuid.UUID,
    user: CurrentUser,
    profile: CurrentProfile,
    session: DbSession,
    access: ActiveAccess,
) -> PlanOut:
    """Replace one meal without touching the rest of the day.

    Implemented as "pin the other meals, exclude this dish, re-solve the day" rather
    than swapping a single dish in place: only a re-solve can promise that the day
    still satisfies its budget and macros afterwards.
    """
    plan = await _owned_plan(session, plan_id, user.id)
    item = await session.get(MealPlanItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    day_row = await session.get(MealPlanDay, item.day_id)
    if day_row is None or day_row.plan_id != plan.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item does not belong to this plan")

    targets = await current_targets(session, user.id)
    if targets is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "compute targets first")

    slug_by_id = {
        rid: slug for rid, slug in (await session.execute(select(Recipe.id, Recipe.slug))).all()
    }
    id_by_slug = {slug: rid for rid, slug in slug_by_id.items()}

    existing = sorted(day_row.items, key=lambda i: list(MealType).index(i.meal_type))
    slots = tuple(i.meal_type for i in existing)
    locked = {
        index: slug_by_id[row.recipe_id]
        for index, row in enumerate(existing)
        if row.id != item.id
    }
    rejected = slug_by_id[item.recipe_id]

    candidates = await load_recipe_candidates(
        session, user.region_code, day_row.day, frozenset(profile.excluded_product_ids or [])
    )
    day_budget = day_row.cost if plan.budget_total is None else plan.budget_total / max(
        1, len(plan.days)
    )
    request = MenuRequest(
        targets=DayTargets(
            kcal=targets.target_kcal,
            protein_g=targets.protein_g,
            fat_g=targets.fat_g,
            carbs_g=targets.carbs_g,
        ),
        budget_per_day=day_budget if plan.budget_total is not None else None,
        meal_slots=slots,
        diet=profile.diet,
        excluded_allergens=catalogue_exclusions(profile.allergens),
        excluded_recipe_ids=frozenset({rejected}),
    )
    new_day = await run_in_threadpool(build_day, candidates, request, locked=locked)
    if not new_day.items:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "no replacement dish satisfies the constraints"
        )

    for row in list(day_row.items):
        await session.delete(row)
    day_row.items.clear()
    await session.flush()

    for planned in new_day.items:
        nutrients = planned.nutrients
        session.add(
            MealPlanItem(
                day_id=day_row.id,
                recipe_id=id_by_slug[planned.recipe.id],
                meal_type=planned.meal_type,
                grams=planned.grams,
                kcal=round(nutrients.kcal, 1),
                protein_g=round(nutrients.protein_g, 1),
                fat_g=round(nutrients.fat_g, 1),
                carbs_g=round(nutrients.carbs_g, 1),
                cost=round(planned.cost, 2),
            )
        )

    previous_cost = day_row.cost
    day_row.kcal = round(new_day.totals.kcal, 1)
    day_row.protein_g = round(new_day.totals.protein_g, 1)
    day_row.fat_g = round(new_day.totals.fat_g, 1)
    day_row.carbs_g = round(new_day.totals.carbs_g, 1)
    day_row.cost = round(new_day.cost, 2)
    plan.cost_total = round(plan.cost_total - previous_cost + day_row.cost, 2)
    await session.flush()

    # Re-read through a fresh query: `refresh` leaves the already-loaded `days`/`items`
    # collections stale, and touching them later triggers a lazy load with no greenlet
    # context (MissingGreenlet) instead of returning the rebuilt day.
    # Read the id *before* expiring, or resolving `plan.id` is itself expired-attribute
    # IO in a sync frame — the same error one line earlier.
    plan_key = plan.id
    session.expire_all()
    reloaded = await session.scalar(select(MealPlan).where(MealPlan.id == plan_key))
    return await _serialize(session, reloaded)
