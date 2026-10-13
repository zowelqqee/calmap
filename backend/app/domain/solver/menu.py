"""Level 1 of the meal planner: which dishes go on the plate.

Portion sizing (level 2) is a convex problem with an exact solution; *choosing* dishes
is combinatorial and has no closed form, so it is handled here by a seeded randomised
greedy plus local search. Every candidate selection is scored by actually running level
2 on it, which means the two levels can never disagree about what is achievable.

The search is deliberately cheap: with 4 meal slots and 8 alternatives per slot over 3
passes it evaluates fewer than 100 quadratic programs of 4 variables each.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field, replace

from app.domain.enums import DietType, MealType
from app.domain.solver.portions import solve_portions
from app.domain.solver.types import (
    DayPlan,
    DayTargets,
    InfeasibilityReason,
    Nutrients,
    Relaxation,
    RecipeCandidate,
    SolveOptions,
)

#: Cost added to a plan's score for each previous appearance of a dish in the period.
#:
#: This has to be calibrated against the units of `DayPlan.score`, which is a sum of
#: weighted squared *relative* deviations: a 4% miss on energy (weight 3.0) scores
#: 3.0 * 0.04^2 = 0.0048. So 0.005 means "swap to a fresh dish unless doing so costs
#: more than about four percent of accuracy".
#:
#: Getting this wrong is not a subtle bug: at 0.35 a single repeat outweighed a 30%
#: calorie miss, and every day after the second in a week silently drifted off target.
REPEAT_PENALTY = 0.005

DEFAULT_SLOTS: tuple[MealType, ...] = (
    MealType.BREAKFAST,
    MealType.LUNCH,
    MealType.DINNER,
    MealType.SNACK,
)


@dataclass(frozen=True, slots=True)
class MenuRequest:
    targets: DayTargets
    budget_per_day: float | None = None
    meal_slots: tuple[MealType, ...] = DEFAULT_SLOTS
    diet: DietType = DietType.OMNIVORE
    excluded_allergens: frozenset[str] = field(default_factory=frozenset)
    excluded_recipe_ids: frozenset[str] = field(default_factory=frozenset)


def filter_candidates(
    recipes: list[RecipeCandidate], request: MenuRequest
) -> list[RecipeCandidate]:
    """Apply the hard, non-negotiable filters: allergens, diet, explicit exclusions."""
    out: list[RecipeCandidate] = []
    for recipe in recipes:
        if recipe.id in request.excluded_recipe_ids:
            continue
        if recipe.allergens & request.excluded_allergens:
            continue
        if not request.diet.allows(recipe.tags):
            continue
        out.append(recipe)
    return out


def _score(plan: DayPlan, usage: Counter[str]) -> float:
    """Nutrition error plus a repetition penalty that grows with each reappearance.

    Superlinear on purpose. A flat penalty forces an impossible choice: set it high and
    variety overrides accuracy on every later day; set it low and the cheapest efficient
    dish shows up six days out of seven. Squaring makes the first repeat almost free
    (0.005 ~ a 4% energy miss) while a fourth appearance costs 0.08 — about a 16% miss,
    which no sane alternative loses to.
    """
    penalty = sum(REPEAT_PENALTY * usage.get(item.recipe.id, 0) ** 2 for item in plan.items)
    return plan.score + penalty


def _can_assign_distinct(choice_sets: list[list[RecipeCandidate]]) -> bool:
    """Whether every slot can receive a different recipe from its fresh choices."""
    if not choice_sets:
        return True
    ordered = sorted(choice_sets, key=len)

    def visit(position: int, taken: set[str]) -> bool:
        if position == len(ordered):
            return True
        for recipe in ordered[position]:
            if recipe.id not in taken and visit(position + 1, taken | {recipe.id}):
                return True
        return False

    return visit(0, set())


def build_day(
    recipes: list[RecipeCandidate],
    request: MenuRequest,
    options: SolveOptions | None = None,
    usage: Counter[str] | None = None,
    locked: dict[int, str] | None = None,
    seed_offset: int = 0,
    avoid_recipe_ids: frozenset[str] | None = None,
) -> DayPlan:
    """Pick dishes for one day and size them.

    `locked` maps a slot index to a recipe id that must stay put — this is what powers
    "regenerate just my dinner" without disturbing the rest of the day.
    """
    options = options or SolveOptions()
    usage = usage or Counter()
    locked = locked or {}
    avoid_recipe_ids = avoid_recipe_ids or frozenset()
    rng = random.Random(options.random_seed + seed_offset)

    pool = filter_candidates(recipes, request)
    by_id = {r.id: r for r in pool}

    matching_by_slot: list[list[RecipeCandidate]] = []
    missing_slots: list[MealType] = []
    for meal_type in request.meal_slots:
        matching = [r for r in pool if meal_type in r.meal_types]
        if not matching:
            missing_slots.append(meal_type)
        matching_by_slot.append(matching)

    fresh_by_slot = [
        [r for r in choices if r.id not in avoid_recipe_ids]
        for choices in matching_by_slot
    ]
    # Use a fresh daily menu only when it can cover every active slot distinctly.
    # Otherwise retain the complete candidate pool: this avoids replacing a balanced
    # day with the same dish repeated across several meals.
    fresh_for_active = [
        fresh for fresh, matching in zip(fresh_by_slot, matching_by_slot, strict=True) if matching
    ]
    use_fresh = bool(avoid_recipe_ids) and all(fresh_for_active) and _can_assign_distinct(
        fresh_for_active
    )
    per_slot = [
        fresh if use_fresh else matching
        for fresh, matching in zip(fresh_by_slot, matching_by_slot, strict=True)
    ]

    relaxations: list[Relaxation] = []
    if missing_slots:
        relaxations.append(
            Relaxation(
                reason=InfeasibilityReason.NOT_ENOUGH_CANDIDATES,
                detail=(
                    "no dishes available for: "
                    + ", ".join(sorted(m.value for m in missing_slots))
                ),
                numbers={"catalogue_size": float(len(pool))},
            )
        )

    active = [
        (index, meal_type, choices)
        for index, (meal_type, choices) in enumerate(zip(request.meal_slots, per_slot, strict=True))
        if choices
    ]
    if not active:
        return DayPlan(
            items=(),
            totals=Nutrients(),
            cost=0.0,
            score=math.inf,
            relaxations=tuple(relaxations)
            or (
                Relaxation(
                    reason=InfeasibilityReason.NOT_ENOUGH_CANDIDATES,
                    detail="the catalogue is empty after filtering",
                ),
            ),
        )

    def evaluate(selection: list[RecipeCandidate]) -> DayPlan:
        pairs = [
            (recipe, meal_type)
            for recipe, (_, meal_type, _) in zip(selection, active, strict=True)
        ]
        return solve_portions(pairs, request.targets, request.budget_per_day, options)

    def free_of_duplicates(
        choices: list[RecipeCandidate], selection: list[RecipeCandidate], position: int
    ) -> list[RecipeCandidate]:
        """Nobody wants the same dish twice in one day — but an exhausted catalogue
        must still produce a plan, so fall back to allowing repeats."""
        taken = {r.id for i, r in enumerate(selection) if i != position and r is not None}
        distinct = [r for r in choices if r.id not in taken]
        return distinct or choices

    # --- initial selection: prefer dishes not used recently, break ties randomly ---
    selection: list[RecipeCandidate | None] = [None] * len(active)
    for position, (index, _meal_type, choices) in enumerate(active):
        pinned = locked.get(index)
        if pinned and pinned in by_id and by_id[pinned] in choices:
            selection[position] = by_id[pinned]
            continue
        available = free_of_duplicates(choices, selection, position)
        weighted = sorted(available, key=lambda r: (usage.get(r.id, 0), rng.random()))
        selection[position] = weighted[0]
    selection = [r for r in selection]  # type: ignore[assignment]

    best = evaluate(selection)
    best_score = _score(best, usage)

    # --- local search: swap one slot at a time, keep improvements ---
    for _pass in range(options.local_search_passes):
        improved = False
        for position, (index, _meal_type, choices) in enumerate(active):
            if index in locked:
                continue
            alternatives = [
                r
                for r in free_of_duplicates(choices, selection, position)
                if r.id != selection[position].id
            ]
            if not alternatives:
                continue
            rng.shuffle(alternatives)
            for alternative in alternatives[: options.alternatives_per_slot]:
                trial = list(selection)
                trial[position] = alternative
                plan = evaluate(trial)
                score = _score(plan, usage)
                if score < best_score - 1e-9:
                    selection, best, best_score, improved = trial, plan, score, True
        if not improved:
            break

    if relaxations:
        best = replace(best, relaxations=tuple(relaxations) + best.relaxations)
    return best


def build_period(
    recipes: list[RecipeCandidate],
    request: MenuRequest,
    days: int,
    total_budget: float | None = None,
    options: SolveOptions | None = None,
) -> list[DayPlan]:
    """Build consecutive days, spreading a period budget and avoiding repetition.

    When `total_budget` is given (the "fixed sum per week" onboarding option) the daily
    allowance is recomputed from what is actually left, so a cheap Monday buys a better
    Sunday instead of the leftover money evaporating.
    """
    options = options or SolveOptions()
    usage: Counter[str] = Counter()
    plans: list[DayPlan] = []
    remaining_budget = total_budget

    for day_index in range(days):
        if remaining_budget is not None:
            per_day: float | None = remaining_budget / (days - day_index)
        else:
            per_day = request.budget_per_day

        day_request = replace(request, budget_per_day=per_day)
        plan = build_day(
            recipes,
            day_request,
            options=options,
            usage=usage,
            seed_offset=day_index * 1013,
            avoid_recipe_ids=frozenset(usage),
        )
        plans.append(plan)
        for item in plan.items:
            usage[item.recipe.id] += 1
        if remaining_budget is not None:
            remaining_budget = max(0.0, remaining_budget - plan.cost)

    return plans
