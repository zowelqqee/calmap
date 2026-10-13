from datetime import date

import pytest

from app.domain.enums import ActivityLevel, Goal, Sex
from app.domain.targets import (
    BodyProfile,
    TargetsError,
    age_from_birth_date,
    basal_metabolic_rate,
    compute_targets,
)


def test_age_from_birth_date_handles_birthday_not_yet_reached():
    assert age_from_birth_date(date(1990, 12, 31), today=date(2026, 8, 3)) == 35
    assert age_from_birth_date(date(1990, 8, 3), today=date(2026, 8, 3)) == 36
    assert age_from_birth_date(date(1990, 8, 4), today=date(2026, 8, 3)) == 35


def test_bmr_matches_mifflin_st_jeor_reference_values():
    male = BodyProfile(sex=Sex.MALE, age=30, height_cm=180, weight_kg=80)
    # 10*80 + 6.25*180 - 5*30 + 5 = 800 + 1125 - 150 + 5
    assert basal_metabolic_rate(male) == pytest.approx(1780.0)

    female = BodyProfile(sex=Sex.FEMALE, age=30, height_cm=165, weight_kg=60)
    # 10*60 + 6.25*165 - 5*30 - 161 = 600 + 1031.25 - 150 - 161
    assert basal_metabolic_rate(female) == pytest.approx(1320.25)


@pytest.mark.parametrize(
    ("level", "coefficient"),
    [(ActivityLevel.LOW, 1.2), (ActivityLevel.MEDIUM, 1.55), (ActivityLevel.HIGH, 1.9)],
)
def test_activity_coefficients_match_the_onboarding_spec(level, coefficient):
    assert level.coefficient == coefficient


def test_maintain_goal_targets_equal_tdee():
    profile = BodyProfile(sex=Sex.MALE, age=30, height_cm=180, weight_kg=80)
    targets = compute_targets(profile, ActivityLevel.MEDIUM, Goal.MAINTAIN)
    assert targets.target_kcal == targets.tdee_kcal
    assert targets.tdee_kcal == round(1780.0 * 1.55)


def test_fixed_deficit_and_surplus_are_applied_relative_to_tdee():
    profile = BodyProfile(sex=Sex.MALE, age=30, height_cm=180, weight_kg=80)
    tdee = compute_targets(profile, ActivityLevel.MEDIUM, Goal.MAINTAIN).tdee_kcal

    cut = compute_targets(profile, ActivityLevel.MEDIUM, Goal.LOSE, rate_pct=0.20)
    assert cut.target_kcal == round(tdee * 0.85)

    bulk = compute_targets(profile, ActivityLevel.MEDIUM, Goal.GAIN, rate_pct=0.10)
    assert bulk.target_kcal == round(tdee * 1.15)


def test_custom_rate_is_ignored_by_the_fixed_product_policy():
    profile = BodyProfile(sex=Sex.FEMALE, age=28, height_cm=168, weight_kg=65)
    targets = compute_targets(profile, ActivityLevel.MEDIUM, Goal.LOSE, rate_pct=0.60)
    normal = compute_targets(profile, ActivityLevel.MEDIUM, Goal.LOSE)
    assert targets.target_kcal == normal.target_kcal
    assert targets.target_kcal >= 1200


def test_safety_floor_prevents_dangerous_targets():
    # Small, sedentary profile with the maximum permitted deficit.
    profile = BodyProfile(sex=Sex.FEMALE, age=60, height_cm=150, weight_kg=45)
    targets = compute_targets(profile, ActivityLevel.LOW, Goal.LOSE, rate_pct=0.25)
    assert targets.target_kcal >= 1200
    assert targets.target_kcal >= round(targets.bmr_kcal * 1.1)
    assert "raised_to_safety_floor" in targets.adjustments


def test_macros_add_up_to_the_energy_target():
    profile = BodyProfile(sex=Sex.MALE, age=27, height_cm=183, weight_kg=88)
    targets = compute_targets(profile, ActivityLevel.HIGH, Goal.GAIN)
    # Rounding to whole grams costs a few kcal; anything beyond 1% is a bug.
    assert targets.macro_kcal == pytest.approx(targets.target_kcal, rel=0.01)


def test_macros_follow_the_documented_30_25_45_split():
    profile = BodyProfile(sex=Sex.MALE, age=27, height_cm=183, weight_kg=88)
    targets = compute_targets(profile, ActivityLevel.HIGH, Goal.LOSE)
    assert targets.protein_g == pytest.approx(targets.target_kcal * 0.30 / 4, abs=1)
    assert targets.fat_g == pytest.approx(targets.target_kcal * 0.25 / 9, abs=1)
    assert targets.carbs_g == pytest.approx(targets.target_kcal * 0.45 / 4, abs=1)


def test_extreme_case_keeps_the_documented_macro_split():
    profile = BodyProfile(sex=Sex.MALE, age=55, height_cm=170, weight_kg=140)
    targets = compute_targets(profile, ActivityLevel.LOW, Goal.LOSE, rate_pct=0.25)
    assert targets.carbs_g == pytest.approx(targets.target_kcal * 0.45 / 4, abs=1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sex": Sex.MALE, "age": 8, "height_cm": 180, "weight_kg": 80},
        {"sex": Sex.MALE, "age": 30, "height_cm": 90, "weight_kg": 80},
        {"sex": Sex.MALE, "age": 30, "height_cm": 180, "weight_kg": 12},
    ],
)
def test_implausible_body_metrics_are_rejected(kwargs):
    with pytest.raises(TargetsError):
        BodyProfile(**kwargs)
