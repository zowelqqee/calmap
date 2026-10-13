"""Orchestration between the questionnaire, the target maths and the solver."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MealPlan, MealPlanDay, MealPlanItem, Recipe, User, UserProfile, UserTargets
from app.domain.enums import BudgetType, MealType
from app.domain.solver import (
    DEFAULT_SLOTS,
    DayPlan,
    DayTargets,
    MenuRequest,
    SolveOptions,
    build_period,
)
from app.domain.targets import BodyProfile, Targets, age_from_birth_date, compute_targets
from app.services.catalog import load_recipe_candidates

DEFAULT_PLAN_DAYS = 7


def targets_for_profile(profile: UserProfile, today: date | None = None) -> Targets:
    body = BodyProfile(
        sex=profile.sex,
        age=age_from_birth_date(profile.birth_date, today),
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
    )
    return compute_targets(body, profile.activity_level, profile.goal, profile.rate_pct)


async def store_targets(session: AsyncSession, user_id: uuid.UUID, targets: Targets) -> UserTargets:
    """Write a new current target row, demoting the previous one (history is kept)."""
    await session.execute(
        update(UserTargets)
        .where(UserTargets.user_id == user_id, UserTargets.is_current.is_(True))
        .values(is_current=False)
    )
    row = UserTargets(
        user_id=user_id,
        bmr_kcal=targets.bmr_kcal,
        tdee_kcal=targets.tdee_kcal,
        target_kcal=targets.target_kcal,
        protein_g=targets.protein_g,
        fat_g=targets.fat_g,
        carbs_g=targets.carbs_g,
        fiber_g=targets.fiber_g,
        water_ml=targets.water_ml,
        adjustments=list(targets.adjustments),
        is_current=True,
    )
    session.add(row)
    await session.flush()
    return row


async def current_targets(session: AsyncSession, user_id: uuid.UUID) -> UserTargets | None:
    return await session.scalar(
        select(UserTargets)
        .where(UserTargets.user_id == user_id, UserTargets.is_current.is_(True))
        .order_by(UserTargets.created_at.desc())
        .limit(1)
    )


def _budget_for_period(profile: UserProfile, days: int) -> float | None:
    """Total money available for `days` days, or None for the unlimited option."""
    if profile.budget_type is BudgetType.UNLIMITED or profile.budget_amount is None:
        return None
    if profile.budget_type is BudgetType.FIXED_DAY:
        return profile.budget_amount * days
    return profile.budget_amount * days / 7.0  # weekly options


async def generate_meal_plan(
    session: AsyncSession,
    user: User,
    profile: UserProfile,
    targets: UserTargets,
    date_from: date | None = None,
    days: int = DEFAULT_PLAN_DAYS,
    meal_slots: tuple[MealType, ...] | None = None,
    exclude_recipe_ids: frozenset[str] = frozenset(),
    options: SolveOptions | None = None,
) -> MealPlan:
    date_from = date_from or date.today()
    candidates = await load_recipe_candidates(session, user.region_code, date_from)

    day_targets = DayTargets(
        kcal=targets.target_kcal,
        protein_g=targets.protein_g,
        fat_g=targets.fat_g,
        carbs_g=targets.carbs_g,
    )
    request = MenuRequest(
        targets=day_targets,
        meal_slots=meal_slots or DEFAULT_SLOTS,
        diet=profile.diet,
        excluded_allergens=frozenset(profile.allergens or []),
        excluded_recipe_ids=exclude_recipe_ids,
    )
    total_budget = _budget_for_period(profile, days)
    day_plans = build_period(
        candidates, request, days=days, total_budget=total_budget, options=options
    )

    return await persist_plan(
        session,
        user_id=user.id,
        date_from=date_from,
        day_plans=day_plans,
        target_kcal=targets.target_kcal,
        budget_total=total_budget,
        currency=profile.currency,
    )


async def persist_plan(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    date_from: date,
    day_plans: list[DayPlan],
    target_kcal: int,
    budget_total: float | None,
    currency: str,
) -> MealPlan:
    recipe_ids = {
        slug: rid
        for slug, rid in (
            await session.execute(select(Recipe.slug, Recipe.id))
        ).all()
    }

    relaxations: list[dict] = []
    for offset, day_plan in enumerate(day_plans):
        for relaxation in day_plan.relaxations:
            entry = asdict(relaxation)
            entry["reason"] = relaxation.reason.value
            entry["day_offset"] = offset
            relaxations.append(entry)

    plan = MealPlan(
        user_id=user_id,
        date_from=date_from,
        date_to=date_from + timedelta(days=len(day_plans) - 1),
        status="ready",
        target_kcal=target_kcal,
        budget_total=budget_total,
        cost_total=round(sum(d.cost for d in day_plans), 2),
        currency=currency,
        relaxations=relaxations,
    )
    session.add(plan)
    await session.flush()

    for offset, day_plan in enumerate(day_plans):
        day_row = MealPlanDay(
            plan_id=plan.id,
            day=date_from + timedelta(days=offset),
            kcal=round(day_plan.totals.kcal, 1),
            protein_g=round(day_plan.totals.protein_g, 1),
            fat_g=round(day_plan.totals.fat_g, 1),
            carbs_g=round(day_plan.totals.carbs_g, 1),
            cost=round(day_plan.cost, 2),
        )
        session.add(day_row)
        await session.flush()

        for item in day_plan.items:
            nutrients = item.nutrients
            session.add(
                MealPlanItem(
                    day_id=day_row.id,
                    recipe_id=recipe_ids[item.recipe.id],
                    meal_type=item.meal_type,
                    grams=item.grams,
                    kcal=round(nutrients.kcal, 1),
                    protein_g=round(nutrients.protein_g, 1),
                    fat_g=round(nutrients.fat_g, 1),
                    carbs_g=round(nutrients.carbs_g, 1),
                    cost=round(item.cost, 2),
                )
            )

    await session.flush()
    return plan


async def shopping_list(
    session: AsyncSession, plan: MealPlan, region_code: str, day: date | None = None
) -> list[dict]:
    """Aggregate a plan into products to buy, costed at the prices used for the plan."""
    from app.db.models import RecipeItem  # local import keeps the module import graph flat

    rows = await session.execute(
        select(MealPlanItem.recipe_id, MealPlanItem.grams, MealPlanItem.day_id)
        .join(MealPlanDay, MealPlanDay.id == MealPlanItem.day_id)
        .where(MealPlanDay.plan_id == plan.id)
    )
    if day is not None:
        rows = await session.execute(
            select(MealPlanItem.recipe_id, MealPlanItem.grams, MealPlanItem.day_id)
            .join(MealPlanDay, MealPlanDay.id == MealPlanItem.day_id)
            .where(MealPlanDay.plan_id == plan.id, MealPlanDay.day == day)
        )
    portions: dict[uuid.UUID, float] = {}
    for recipe_id, grams, _day_id in rows:
        portions[recipe_id] = portions.get(recipe_id, 0.0) + grams

    if not portions:
        return []

    recipes = {
        r.id: r
        for r in (
            await session.scalars(select(Recipe).where(Recipe.id.in_(portions)))
        ).all()
    }
    item_rows = (
        await session.scalars(
            select(RecipeItem).where(RecipeItem.recipe_id.in_(portions))
        )
    ).all()

    needed: dict[str, dict] = {}
    for item in item_rows:
        recipe = recipes[item.recipe_id]
        # Scale each ingredient by how much of the dish the plan actually calls for.
        scale = portions[recipe.id] / recipe.base_grams
        grams = item.grams * scale
        entry = needed.setdefault(
            item.product.slug,
            {"slug": item.product.slug, "name": item.product.name,
             "category": item.product.category, "grams": 0.0},
        )
        entry["grams"] += grams

    from app.services.catalog import current_prices_per_kg

    prices = await current_prices_per_kg(session, region_code, plan.date_from)
    out = []
    for entry in needed.values():
        price_per_kg = prices.get(entry["slug"])
        entry["grams"] = round(entry["grams"])
        entry["estimated_cost"] = (
            round(price_per_kg * entry["grams"] / 1000.0, 2) if price_per_kg else None
        )
        entry["store"] = "Средняя цена по Москве"
        out.append(entry)
    return sorted(out, key=lambda e: (e["category"], e["name"]))
