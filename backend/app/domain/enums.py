from enum import StrEnum


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Goal(StrEnum):
    LOSE = "lose"
    MAINTAIN = "maintain"
    GAIN = "gain"


class ActivityLevel(StrEnum):
    """Three levels per the onboarding spec, with their TDEE coefficients."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def coefficient(self) -> float:
        return _ACTIVITY_COEFFICIENTS[self]


_ACTIVITY_COEFFICIENTS: dict[ActivityLevel, float] = {
    ActivityLevel.LOW: 1.2,
    ActivityLevel.MEDIUM: 1.55,
    ActivityLevel.HIGH: 1.9,
}


class WorkoutLocation(StrEnum):
    HOME = "home"
    GYM = "gym"


class BudgetType(StrEnum):
    FIXED_DAY = "fixed_day"
    FIXED_WEEK = "fixed_week"
    UNLIMITED = "unlimited"
    CUSTOM_WEEK = "custom_week"


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class DietType(StrEnum):
    OMNIVORE = "omnivore"
    NO_PORK = "no_pork"
    PESCATARIAN = "pescatarian"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"

    def allows(self, tags: frozenset[str]) -> bool:
        """`tags` are product/recipe markers such as {'meat', 'pork', 'fish', 'dairy', 'egg'}."""
        forbidden = _DIET_FORBIDDEN_TAGS[self]
        return not (tags & forbidden)


_DIET_FORBIDDEN_TAGS: dict[DietType, frozenset[str]] = {
    DietType.OMNIVORE: frozenset(),
    DietType.NO_PORK: frozenset({"pork"}),
    DietType.PESCATARIAN: frozenset({"meat", "pork", "poultry"}),
    DietType.VEGETARIAN: frozenset({"meat", "pork", "poultry", "fish", "seafood"}),
    DietType.VEGAN: frozenset({"meat", "pork", "poultry", "fish", "seafood", "dairy", "egg", "honey"}),
}
