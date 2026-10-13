"""Energy and macronutrient targets.

Pure functions, no I/O, no framework imports — this module is the single source of
truth for every number the user sees on the "your plan" screen, so it is covered by
unit tests rather than trusted to an LLM at runtime.

References for the constants used here:
  * Mifflin-St Jeor (1990) resting metabolic rate equation — the current default in
    clinical practice, more accurate than Harris-Benedict for modern populations.
  * Macronutrients follow the product specification: 30% protein, 25% fat,
    45% carbohydrates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.domain.enums import ActivityLevel, Goal, Sex

KCAL_PER_G_PROTEIN = 4.0
KCAL_PER_G_CARBS = 4.0
KCAL_PER_G_FAT = 9.0

# Hard safety floors. A nutrition app must never hand a user a number below these,
# whatever the requested deficit is.
ABSOLUTE_KCAL_FLOOR: dict[Sex, int] = {Sex.FEMALE: 1200, Sex.MALE: 1500}
# ...and never below resting metabolism plus a small margin.
BMR_FLOOR_MULTIPLIER = 1.1

# Caps on what the onboarding slider may request, as a fraction of TDEE.
MAX_DEFICIT_PCT = 0.25
MAX_SURPLUS_PCT = 0.20

DEFAULT_RATE_PCT: dict[Goal, float] = {
    Goal.LOSE: 0.15,
    Goal.MAINTAIN: 0.0,
    Goal.GAIN: 0.15,
}

PROTEIN_PCT_OF_KCAL = 0.30
FAT_PCT_OF_KCAL = 0.25
CARBS_PCT_OF_KCAL = 0.45


class TargetsError(ValueError):
    """Raised when the inputs cannot produce a safe plan."""


def age_from_birth_date(birth_date: date, today: date | None = None) -> int:
    today = today or date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


@dataclass(frozen=True, slots=True)
class BodyProfile:
    sex: Sex
    age: int
    height_cm: float
    weight_kg: float

    def __post_init__(self) -> None:
        if not 10 <= self.age <= 99:
            raise TargetsError("age must be between 10 and 99")
        if not 100 <= self.height_cm <= 250:
            raise TargetsError("height_cm must be between 100 and 250")
        if not 30 <= self.weight_kg <= 300:
            raise TargetsError("weight_kg must be between 30 and 300")


@dataclass(frozen=True, slots=True)
class Targets:
    bmr_kcal: int
    tdee_kcal: int
    target_kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int
    fiber_g: int
    water_ml: int
    #: Set when a safety floor overrode the requested deficit — surface this in the UI.
    adjustments: tuple[str, ...] = field(default=())

    @property
    def macro_kcal(self) -> float:
        return (
            self.protein_g * KCAL_PER_G_PROTEIN
            + self.carbs_g * KCAL_PER_G_CARBS
            + self.fat_g * KCAL_PER_G_FAT
        )


def basal_metabolic_rate(profile: BodyProfile) -> float:
    """Mifflin-St Jeor."""
    base = 10.0 * profile.weight_kg + 6.25 * profile.height_cm - 5.0 * profile.age
    return base + (5.0 if profile.sex is Sex.MALE else -161.0)


def total_daily_energy_expenditure(profile: BodyProfile, activity: ActivityLevel) -> float:
    return basal_metabolic_rate(profile) * activity.coefficient


def compute_targets(
    profile: BodyProfile,
    activity: ActivityLevel,
    goal: Goal,
    rate_pct: float | None = None,
) -> Targets:
    """Full plan for one day.

    `rate_pct` is the deficit (goal=lose) or surplus (goal=gain) as a fraction of TDEE,
    e.g. 0.18 for -18%. `None` uses the default for the goal.
    """
    bmr = basal_metabolic_rate(profile)
    tdee = bmr * activity.coefficient
    adjustments: list[str] = []

    # The final product specification deliberately has no user-controlled slider:
    # lose = -15%, maintain = 0%, gain = +15%. Keep the parameter for backwards
    # compatibility with older clients, but never let it alter the documented plan.
    rate = DEFAULT_RATE_PCT[goal]

    if goal is Goal.LOSE:
        target = tdee * (1.0 - rate)
    elif goal is Goal.GAIN:
        target = tdee * (1.0 + rate)
    else:
        target = tdee

    floor = max(ABSOLUTE_KCAL_FLOOR[profile.sex], bmr * BMR_FLOOR_MULTIPLIER)
    if target < floor:
        target = floor
        adjustments.append("raised_to_safety_floor")

    protein_g = target * PROTEIN_PCT_OF_KCAL / KCAL_PER_G_PROTEIN
    fat_g = target * FAT_PCT_OF_KCAL / KCAL_PER_G_FAT
    carbs_g = target * CARBS_PCT_OF_KCAL / KCAL_PER_G_CARBS

    return Targets(
        bmr_kcal=round(bmr),
        tdee_kcal=round(tdee),
        target_kcal=round(target),
        protein_g=round(protein_g),
        fat_g=round(fat_g),
        carbs_g=round(carbs_g),
        fiber_g=round(min(38.0, max(25.0, target / 1000.0 * 14.0))),
        water_ml=round(profile.weight_kg * 33.0),
        adjustments=tuple(adjustments),
    )
