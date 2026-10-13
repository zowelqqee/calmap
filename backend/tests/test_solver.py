from collections import Counter

import pytest

from app.domain.enums import DietType, MealType
from app.domain.solver import (
    DayTargets,
    InfeasibilityReason,
    MenuRequest,
    Nutrients,
    RecipeCandidate,
    SolveOptions,
    build_day,
    build_period,
    filter_candidates,
    solve_portions,
)

ALL_MEALS = frozenset(MealType)


def recipe(
    rid: str,
    *,
    kcal: float,
    protein: float,
    fat: float,
    carbs: float,
    price: float,
    meals: frozenset[MealType] = ALL_MEALS,
    tags: frozenset[str] = frozenset(),
    allergens: frozenset[str] = frozenset(),
    min_grams: float = 80.0,
    max_grams: float = 450.0,
) -> RecipeCandidate:
    return RecipeCandidate(
        id=rid,
        name=rid,
        meal_types=meals,
        nutrients_per_100g=Nutrients(kcal=kcal, protein_g=protein, fat_g=fat, carbs_g=carbs),
        price_per_100g=price,
        min_grams=min_grams,
        max_grams=max_grams,
        tags=tags,
        allergens=allergens,
    )


CHICKEN_RICE = recipe("chicken_rice", kcal=150, protein=12, fat=3, carbs=19, price=38, tags=frozenset({"poultry"}))
OATS = recipe("oats", kcal=170, protein=6, fat=5, carbs=25, price=22, meals=frozenset({MealType.BREAKFAST}))
COTTAGE = recipe("cottage_cheese", kcal=120, protein=17, fat=4, carbs=3, price=45, tags=frozenset({"dairy"}), allergens=frozenset({"lactose"}))
FISH_VEG = recipe("fish_veg", kcal=110, protein=14, fat=4, carbs=5, price=70, tags=frozenset({"fish"}))
PASTA_PORK = recipe("pasta_pork", kcal=210, protein=9, fat=9, carbs=24, price=33, tags=frozenset({"meat", "pork"}))
NUTS = recipe("nuts", kcal=600, protein=20, fat=54, carbs=12, price=180, meals=frozenset({MealType.SNACK}), allergens=frozenset({"nuts"}), min_grams=20, max_grams=60)

CATALOGUE = [CHICKEN_RICE, OATS, COTTAGE, FISH_VEG, PASTA_PORK, NUTS]

TARGETS = DayTargets(kcal=2400, protein_g=170, fat_g=75, carbs_g=245)


# --------------------------------------------------------------------------- level 2


def test_portions_hit_the_targets_when_the_catalogue_allows_it():
    pairs = [
        (OATS, MealType.BREAKFAST),
        (CHICKEN_RICE, MealType.LUNCH),
        (FISH_VEG, MealType.DINNER),
        (COTTAGE, MealType.SNACK),
    ]
    plan = solve_portions(pairs, TARGETS, budget=None)
    deviations = plan.deviations(TARGETS)
    assert abs(deviations["kcal"]) < 0.10
    assert abs(deviations["protein_g"]) < 0.15


def test_portions_never_exceed_the_budget():
    pairs = [(OATS, MealType.BREAKFAST), (CHICKEN_RICE, MealType.LUNCH), (FISH_VEG, MealType.DINNER)]
    budget = 400.0
    plan = solve_portions(pairs, TARGETS, budget=budget)
    assert plan.cost <= budget + 1e-6


def test_portions_respect_edible_bounds():
    pairs = [(NUTS, MealType.SNACK), (CHICKEN_RICE, MealType.LUNCH)]
    plan = solve_portions(pairs, TARGETS, budget=None)
    for item in plan.items:
        assert item.recipe.min_grams - 1e-9 <= item.grams <= item.recipe.max_grams + 1e-9


def test_portions_are_rounded_to_a_scale_friendly_step():
    pairs = [(OATS, MealType.BREAKFAST), (CHICKEN_RICE, MealType.LUNCH)]
    plan = solve_portions(pairs, TARGETS, budget=None, options=SolveOptions(grams_step=5.0))
    for item in plan.items:
        assert item.grams % 5 == pytest.approx(0.0)


def test_impossible_budget_reports_a_relaxation_instead_of_failing():
    pairs = [(FISH_VEG, MealType.DINNER), (NUTS, MealType.SNACK)]
    plan = solve_portions(pairs, TARGETS, budget=10.0)
    assert plan.items, "a plan must still be returned"
    reasons = {r.reason for r in plan.relaxations}
    assert InfeasibilityReason.BUDGET_TOO_LOW in reasons
    numbers = next(r.numbers for r in plan.relaxations if r.reason is InfeasibilityReason.BUDGET_TOO_LOW)
    assert numbers["minimum_cost"] > numbers["budget"]


def test_empty_candidate_list_is_handled():
    plan = solve_portions([], TARGETS, budget=None)
    assert plan.items == ()
    assert plan.relaxations[0].reason is InfeasibilityReason.NOT_ENOUGH_CANDIDATES


def test_tighter_budget_never_produces_a_better_nutrition_score():
    pairs = [(OATS, MealType.BREAKFAST), (CHICKEN_RICE, MealType.LUNCH), (FISH_VEG, MealType.DINNER)]
    generous = solve_portions(pairs, TARGETS, budget=1000.0)
    tight = solve_portions(pairs, TARGETS, budget=350.0)
    assert tight.score >= generous.score - 1e-9


# --------------------------------------------------------------------------- filters


def test_allergen_exclusion_removes_matching_recipes():
    request = MenuRequest(targets=TARGETS, excluded_allergens=frozenset({"lactose"}))
    kept = {r.id for r in filter_candidates(CATALOGUE, request)}
    assert "cottage_cheese" not in kept
    assert "chicken_rice" in kept


def test_diet_filter_removes_forbidden_tags():
    request = MenuRequest(targets=TARGETS, diet=DietType.VEGETARIAN)
    kept = {r.id for r in filter_candidates(CATALOGUE, request)}
    assert kept == {"oats", "cottage_cheese", "nuts"}


def test_no_pork_diet_keeps_poultry():
    request = MenuRequest(targets=TARGETS, diet=DietType.NO_PORK)
    kept = {r.id for r in filter_candidates(CATALOGUE, request)}
    assert "pasta_pork" not in kept
    assert "chicken_rice" in kept


def test_explicit_exclusions_are_honoured():
    request = MenuRequest(targets=TARGETS, excluded_recipe_ids=frozenset({"oats"}))
    assert "oats" not in {r.id for r in filter_candidates(CATALOGUE, request)}


# --------------------------------------------------------------------------- level 1


def test_build_day_fills_every_slot_and_respects_meal_types():
    request = MenuRequest(targets=TARGETS, budget_per_day=600.0)
    plan = build_day(CATALOGUE, request)
    assert len(plan.items) == 4
    for item in plan.items:
        assert item.meal_type in item.recipe.meal_types


def test_build_day_stays_within_budget():
    request = MenuRequest(targets=TARGETS, budget_per_day=500.0)
    plan = build_day(CATALOGUE, request)
    assert plan.cost <= 500.0 + 1e-6


def test_build_day_is_deterministic_for_a_fixed_seed():
    request = MenuRequest(targets=TARGETS, budget_per_day=600.0)
    first = build_day(CATALOGUE, request, options=SolveOptions(random_seed=7))
    second = build_day(CATALOGUE, request, options=SolveOptions(random_seed=7))
    assert [i.recipe.id for i in first.items] == [i.recipe.id for i in second.items]
    assert [i.grams for i in first.items] == [i.grams for i in second.items]


def test_local_search_improves_on_the_initial_selection():
    request = MenuRequest(targets=TARGETS, budget_per_day=600.0)
    searched = build_day(CATALOGUE, request, options=SolveOptions(local_search_passes=3))
    greedy_only = build_day(CATALOGUE, request, options=SolveOptions(local_search_passes=0))
    assert searched.score <= greedy_only.score + 1e-9


def test_a_dish_is_never_repeated_within_one_day():
    request = MenuRequest(targets=TARGETS, budget_per_day=600.0)
    plan = build_day(CATALOGUE, request)
    ids = [i.recipe.id for i in plan.items]
    assert len(ids) == len(set(ids))


def test_duplicates_are_allowed_only_when_the_catalogue_is_exhausted():
    single = [CHICKEN_RICE]
    request = MenuRequest(targets=TARGETS, meal_slots=(MealType.LUNCH, MealType.DINNER))
    plan = build_day(single, request)
    assert [i.recipe.id for i in plan.items] == ["chicken_rice", "chicken_rice"]


def test_portions_stay_on_the_grid_even_when_the_budget_binds():
    pairs = [(OATS, MealType.BREAKFAST), (CHICKEN_RICE, MealType.LUNCH), (FISH_VEG, MealType.DINNER)]
    plan = solve_portions(pairs, TARGETS, budget=300.0, options=SolveOptions(grams_step=5.0))
    assert plan.cost <= 300.0 + 1e-6
    for item in plan.items:
        on_grid = item.grams % 5 == pytest.approx(0.0)
        assert on_grid or item.grams == pytest.approx(item.recipe.min_grams)


def test_locked_slot_is_preserved():
    request = MenuRequest(targets=TARGETS, budget_per_day=600.0)
    plan = build_day(CATALOGUE, request, locked={1: "pasta_pork"})
    assert plan.items[1].recipe.id == "pasta_pork"


def test_missing_meal_type_is_reported_but_the_day_is_still_built():
    only_lunch = [replace_meals(CHICKEN_RICE, frozenset({MealType.LUNCH}))]
    request = MenuRequest(targets=TARGETS)
    plan = build_day(only_lunch, request)
    assert len(plan.items) == 1
    assert InfeasibilityReason.NOT_ENOUGH_CANDIDATES in {r.reason for r in plan.relaxations}


def replace_meals(r: RecipeCandidate, meals: frozenset[MealType]) -> RecipeCandidate:
    from dataclasses import replace

    return replace(r, meal_types=meals)


def test_repeat_penalty_pushes_the_planner_towards_variety():
    request = MenuRequest(targets=TARGETS, budget_per_day=600.0)
    usage: Counter[str] = Counter({"chicken_rice": 5, "fish_veg": 5})
    plan = build_day(CATALOGUE, request, usage=usage)
    heavy_repeats = [i.recipe.id for i in plan.items if usage[i.recipe.id] >= 5]
    assert len(heavy_repeats) < len(plan.items)


# --------------------------------------------------------------------------- periods


def test_variety_never_overrides_nutrition_accuracy():
    """Regression: the repeat penalty must stay small relative to the objective.

    With a heavy penalty the planner trades away real accuracy on later days just to
    avoid serving a dish twice, and a week plan quietly drifts 20% under target.
    """
    request = MenuRequest(targets=TARGETS, budget_per_day=800.0)
    plans = build_period(CATALOGUE, request, days=7)
    for index, plan in enumerate(plans):
        worst = max(abs(v) for v in plan.deviations(TARGETS).values())
        assert worst < 0.35, f"day {index} drifted {worst:.0%} off target"


def test_no_dish_dominates_the_week():
    """The other half of the tuning: a penalty that is too weak lets the cheapest
    efficient dish appear almost every day, which reads as a broken plan."""
    request = MenuRequest(targets=TARGETS, budget_per_day=800.0)
    plans = build_period(CATALOGUE, request, days=7)
    counts = Counter(item.recipe.id for plan in plans for item in plan.items)
    distinct_dishes = len({r.id for r in CATALOGUE})
    # With a catalogue this small some repetition is unavoidable; a single dish taking
    # more than half the week's slots is not.
    most_common_share = counts.most_common(1)[0][1] / sum(counts.values())
    assert most_common_share <= 0.5, counts
    assert len(counts) >= min(distinct_dishes, 4)


def test_period_avoids_dishes_used_on_previous_days_when_available():
    request = MenuRequest(targets=TARGETS, meal_slots=(MealType.BREAKFAST,))
    plans = build_period(CATALOGUE, request, days=4)
    ids = [plan.items[0].recipe.id for plan in plans]
    assert len(ids) == len(set(ids))


def test_build_period_returns_one_plan_per_day():
    request = MenuRequest(targets=TARGETS, budget_per_day=600.0)
    plans = build_period(CATALOGUE, request, days=7)
    assert len(plans) == 7


def test_weekly_budget_is_respected_in_aggregate():
    request = MenuRequest(targets=TARGETS)
    weekly = 3500.0
    plans = build_period(CATALOGUE, request, days=7, total_budget=weekly)
    assert sum(p.cost for p in plans) <= weekly + 1e-6


def test_weekly_budget_rolls_savings_forward():
    """A cheap early day should leave a larger allowance for the last day."""
    request = MenuRequest(targets=TARGETS)
    plans = build_period(CATALOGUE, request, days=3, total_budget=1500.0)
    assert sum(p.cost for p in plans) <= 1500.0 + 1e-6
    assert all(p.items for p in plans)
