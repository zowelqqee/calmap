"""Level 2 of the meal planner: exact portion sizing for a fixed set of dishes.

Given the dishes chosen by level 1, decide how many grams of each to serve so that the
day hits its energy and macro targets as closely as possible without exceeding the food
budget.

Formally this is a convex quadratic program

    minimise    sum_m  w_m * ((A_m . x - T_m) / T_m)^2
    subject to  lo <= x <= hi                     (edible portion sizes)
                p . x <= B                        (daily budget)

with four nutrient rows m and one variable per dish. It is solved here with projected
gradient descent; the projection onto {box} ∩ {p.x <= B} is computed exactly by
bisection on the budget multiplier, so the result is a true optimum rather than a
heuristic. Deliberately dependency-free: no numpy, no OR-Tools, no solver binary to
install on a RU-hosted VM. Typical runtime is well under a millisecond for the 3-6
dishes a real day contains.
"""

from __future__ import annotations

import math

from app.domain.solver.types import (
    DayPlan,
    DayTargets,
    InfeasibilityReason,
    Nutrients,
    PlanItem,
    Relaxation,
    RecipeCandidate,
    SolveOptions,
)
from app.domain.enums import MealType

_BISECTION_STEPS = 60


def _project(
    x: list[float],
    lo: list[float],
    hi: list[float],
    prices: list[float],
    budget: float | None,
) -> list[float]:
    """Euclidean projection onto the box intersected with the budget half-space."""
    clipped = [min(max(v, lo[i]), hi[i]) for i, v in enumerate(x)]
    if budget is None:
        return clipped

    cost = sum(clipped[i] * prices[i] for i in range(len(clipped)))
    if cost <= budget:
        return clipped

    # g(lam) = p . clip(x - lam*p, lo, hi) is non-increasing; find the smallest
    # lam >= 0 that brings the cost inside the budget.
    def g(lam: float) -> tuple[float, list[float]]:
        y = [min(max(x[i] - lam * prices[i], lo[i]), hi[i]) for i in range(len(x))]
        return sum(y[i] * prices[i] for i in range(len(y))), y

    lam_hi = 1.0
    cost_hi, y_hi = g(lam_hi)
    for _ in range(_BISECTION_STEPS):
        if cost_hi <= budget:
            break
        lam_hi *= 4.0
        cost_hi, y_hi = g(lam_hi)
    else:
        # Even the minimum portions blow the budget — level 1 must relax something.
        return [lo[i] for i in range(len(x))]

    lam_lo = 0.0
    for _ in range(_BISECTION_STEPS):
        mid = 0.5 * (lam_lo + lam_hi)
        cost_mid, y_mid = g(mid)
        if cost_mid > budget:
            lam_lo = mid
        else:
            lam_hi, y_hi = mid, y_mid
    return y_hi


def _objective(
    x: list[float],
    rows: list[list[float]],
    targets: tuple[float, ...],
    weights: tuple[float, ...],
) -> float:
    total = 0.0
    for m, row in enumerate(rows):
        target = targets[m]
        if target <= 0:
            continue
        achieved = sum(row[i] * x[i] for i in range(len(x)))
        rel = (achieved - target) / target
        total += weights[m] * rel * rel
    return total


def _gradient(
    x: list[float],
    rows: list[list[float]],
    targets: tuple[float, ...],
    weights: tuple[float, ...],
) -> list[float]:
    grad = [0.0] * len(x)
    for m, row in enumerate(rows):
        target = targets[m]
        if target <= 0:
            continue
        achieved = sum(row[i] * x[i] for i in range(len(x)))
        coefficient = 2.0 * weights[m] * (achieved - target) / (target * target)
        for i in range(len(x)):
            grad[i] += coefficient * row[i]
    return grad


def solve_portions(
    candidates: list[tuple[RecipeCandidate, MealType]],
    targets: DayTargets,
    budget: float | None,
    options: SolveOptions | None = None,
) -> DayPlan:
    """Size the portions for one day. Never raises on infeasibility — see `relaxations`."""
    options = options or SolveOptions()

    if not candidates:
        return DayPlan(
            items=(),
            totals=Nutrients(),
            cost=0.0,
            score=math.inf,
            relaxations=(
                Relaxation(
                    reason=InfeasibilityReason.NOT_ENOUGH_CANDIDATES,
                    detail="no dishes matched the diet, allergen and meal-type filters",
                ),
            ),
        )

    recipes = [c for c, _ in candidates]
    n = len(recipes)

    # rows[m][i] = amount of nutrient m contributed by one gram of dish i
    rows: list[list[float]] = []
    for getter in (
        lambda r: r.nutrients_per_100g.kcal,
        lambda r: r.nutrients_per_100g.protein_g,
        lambda r: r.nutrients_per_100g.fat_g,
        lambda r: r.nutrients_per_100g.carbs_g,
    ):
        rows.append([getter(r) / 100.0 for r in recipes])

    prices = [r.price_per_100g / 100.0 for r in recipes]
    lo = [r.min_grams for r in recipes]
    hi = [r.max_grams for r in recipes]
    target_tuple = targets.as_tuple()
    weight_tuple = options.weights.as_tuple()

    relaxations: list[Relaxation] = []
    effective_budget = budget
    min_cost = sum(lo[i] * prices[i] for i in range(n))
    if budget is not None and min_cost > budget:
        relaxations.append(
            Relaxation(
                reason=InfeasibilityReason.BUDGET_TOO_LOW,
                detail=(
                    "the smallest edible portions of the selected dishes already cost more "
                    "than the daily budget"
                ),
                numbers={"budget": round(budget, 2), "minimum_cost": round(min_cost, 2)},
            )
        )
        effective_budget = None  # ignore an impossible constraint rather than return nothing

    # Lipschitz constant of the gradient, used as a fixed safe step size.
    lipschitz = 0.0
    for m, row in enumerate(rows):
        target = target_tuple[m]
        if target <= 0:
            continue
        lipschitz += 2.0 * weight_tuple[m] * sum(v * v for v in row) / (target * target)
    step = 1.0 / lipschitz if lipschitz > 0 else 1.0

    x = _project([r.base_grams for r in recipes], lo, hi, prices, effective_budget)
    previous = _objective(x, rows, target_tuple, weight_tuple)
    for _ in range(options.max_iterations):
        grad = _gradient(x, rows, target_tuple, weight_tuple)
        candidate = _project(
            [x[i] - step * grad[i] for i in range(n)], lo, hi, prices, effective_budget
        )
        current = _objective(candidate, rows, target_tuple, weight_tuple)
        moved = max(abs(candidate[i] - x[i]) for i in range(n))
        x = candidate
        if moved < 1e-4 and abs(previous - current) < 1e-12:
            break
        previous = current

    # Round to a step the kitchen scale can actually show. Re-project first so the
    # budget is respected, then floor to the step: flooring only ever reduces cost, so
    # both the budget and the grid survive. (Rounding *after* projecting to the budget
    # face would otherwise leave values like 449 g.)
    x = _project(x, lo, hi, prices, effective_budget)
    stepsize = options.grams_step
    x = [max(lo[i], math.floor(v / stepsize) * stepsize) for i, v in enumerate(x)]

    items = tuple(
        PlanItem(recipe=recipe, meal_type=meal_type, grams=x[i])
        for i, (recipe, meal_type) in enumerate(candidates)
    )
    totals = Nutrients()
    for item in items:
        totals = totals + item.nutrients
    cost = sum(item.cost for item in items)
    score = _objective(x, rows, target_tuple, weight_tuple)

    plan = DayPlan(items=items, totals=totals, cost=cost, score=score, relaxations=tuple(relaxations))

    worst = max(abs(v) for v in plan.deviations(targets).values())
    if worst > 0.15 and not relaxations:
        relaxations.append(
            Relaxation(
                reason=InfeasibilityReason.TARGETS_UNREACHABLE,
                detail=(
                    "the selected dishes cannot reach the targets within edible portion "
                    "sizes; try widening the catalogue or the budget"
                ),
                numbers={"worst_relative_deviation": round(worst, 4)},
            )
        )
        plan = DayPlan(
            items=plan.items,
            totals=plan.totals,
            cost=plan.cost,
            score=plan.score,
            relaxations=tuple(relaxations),
        )
    return plan
