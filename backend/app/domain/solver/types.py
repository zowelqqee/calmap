from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.enums import MealType

NUTRIENTS = ("kcal", "protein_g", "fat_g", "carbs_g")


@dataclass(frozen=True, slots=True)
class Nutrients:
    """Per-100 g figures for a recipe, or absolute totals for a plan."""

    kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0

    def scaled(self, factor: float) -> Nutrients:
        return Nutrients(
            kcal=self.kcal * factor,
            protein_g=self.protein_g * factor,
            fat_g=self.fat_g * factor,
            carbs_g=self.carbs_g * factor,
        )

    def __add__(self, other: Nutrients) -> Nutrients:
        return Nutrients(
            kcal=self.kcal + other.kcal,
            protein_g=self.protein_g + other.protein_g,
            fat_g=self.fat_g + other.fat_g,
            carbs_g=self.carbs_g + other.carbs_g,
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.kcal, self.protein_g, self.fat_g, self.carbs_g)


@dataclass(frozen=True, slots=True)
class RecipeCandidate:
    """A dish the solver may put on the plate.

    Nutrients and price are per 100 g of the finished dish so that level 2 can scale a
    portion continuously. `min_grams`/`max_grams` keep the result edible: without them
    the optimiser happily proposes 640 g of buckwheat.
    """

    id: str
    name: str
    meal_types: frozenset[MealType]
    nutrients_per_100g: Nutrients
    price_per_100g: float
    base_grams: float = 200.0
    min_grams: float = 80.0
    max_grams: float = 450.0
    tags: frozenset[str] = field(default_factory=frozenset)
    allergens: frozenset[str] = field(default_factory=frozenset)

    def portion(self, grams: float) -> Nutrients:
        return self.nutrients_per_100g.scaled(grams / 100.0)

    def price(self, grams: float) -> float:
        return self.price_per_100g * grams / 100.0


@dataclass(frozen=True, slots=True)
class DayTargets:
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.kcal, self.protein_g, self.fat_g, self.carbs_g)


class InfeasibilityReason(StrEnum):
    BUDGET_TOO_LOW = "budget_too_low"
    NOT_ENOUGH_CANDIDATES = "not_enough_candidates"
    TARGETS_UNREACHABLE = "targets_unreachable"


@dataclass(frozen=True, slots=True)
class Relaxation:
    """What the solver had to give up on, and by how much.

    The product requirement here is that we never answer "no solution": we answer with
    the closest reachable plan plus an explanation the UI can render.
    """

    reason: InfeasibilityReason
    detail: str
    #: e.g. {"budget_rub": 420.0, "required_rub": 517.3}
    numbers: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SolveOptions:
    #: Relative weights of each nutrient in the objective. Energy and protein dominate
    #: because they are what the first-wave audience actually tracks.
    weights: Nutrients = Nutrients(kcal=3.0, protein_g=2.5, fat_g=1.0, carbs_g=1.0)
    #: Acceptable relative deviation before we consider a target "hit".
    tolerance: float = 0.03
    max_iterations: int = 4000
    grams_step: float = 5.0
    #: Level-1 search effort.
    local_search_passes: int = 3
    alternatives_per_slot: int = 8
    random_seed: int = 20260803


@dataclass(frozen=True, slots=True)
class PlanItem:
    recipe: RecipeCandidate
    meal_type: MealType
    grams: float

    @property
    def nutrients(self) -> Nutrients:
        return self.recipe.portion(self.grams)

    @property
    def cost(self) -> float:
        return self.recipe.price(self.grams)


@dataclass(frozen=True, slots=True)
class DayPlan:
    items: tuple[PlanItem, ...]
    totals: Nutrients
    cost: float
    #: Sum of weighted squared relative deviations — lower is better, 0 is perfect.
    score: float
    relaxations: tuple[Relaxation, ...] = field(default=())

    def deviations(self, targets: DayTargets) -> dict[str, float]:
        got = self.totals.as_tuple()
        want = targets.as_tuple()
        return {
            name: (g - w) / w if w else 0.0
            for name, g, w in zip(NUTRIENTS, got, want, strict=True)
        }
