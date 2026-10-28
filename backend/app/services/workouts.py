from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile, Workout, WorkoutExercise
from app.domain.enums import ActivityLevel, Goal
from app.domain.exercises import EQUIPMENT_TYPES, EXERCISES, Exercise


@dataclass(frozen=True, slots=True)
class WorkoutBlueprint:
    title: str
    focus: tuple[str, ...]


# A training day is a muscle split, never a fixed exercise list. Variants are
# selected from the exercise registry below, so the plan can keep rotating as
# the catalogue grows without another scheduler rewrite.
BLUEPRINTS: dict[ActivityLevel, dict[int, WorkoutBlueprint]] = {
    ActivityLevel.LOW: {
        0: WorkoutBlueprint("Всё тело — базовая сила", ("квадрицепсы", "грудь", "ягодицы")),
        3: WorkoutBlueprint("Подвижность и кор", ("разгибатели спины", "кор", "средняя ягодичная")),
    },
    ActivityLevel.MEDIUM: {
        0: WorkoutBlueprint("Верх тела — жим", ("грудь", "передняя дельта", "трицепс")),
        2: WorkoutBlueprint("Ноги и кор", ("квадрицепсы", "задняя поверхность бедра", "ягодицы", "кор")),
        4: WorkoutBlueprint("Спина и руки", ("широчайшие", "верх спины", "бицепс", "предплечья")),
    },
    ActivityLevel.HIGH: {
        0: WorkoutBlueprint("Верх тела — жим", ("грудь", "передняя дельта", "трицепс", "передняя зубчатая")),
        1: WorkoutBlueprint("Ноги — сила", ("квадрицепсы", "задняя поверхность бедра", "ягодицы", "икры")),
        3: WorkoutBlueprint("Спина и руки", ("широчайшие", "верх спины", "задняя дельта", "бицепс", "предплечья")),
        4: WorkoutBlueprint("Ноги — устойчивость", ("средняя ягодичная", "приводящие мышцы бедра", "сгибатели бедра", "камбаловидная", "кор")),
        5: WorkoutBlueprint("Всё тело и кондиция", ("всё тело", "трапеции", "косые мышцы живота", "вращательная манжета")),
    },
}

DIFFICULTIES: dict[ActivityLevel, frozenset[str]] = {
    ActivityLevel.LOW: frozenset({"начальный"}),
    ActivityLevel.MEDIUM: frozenset({"начальный", "средний"}),
    ActivityLevel.HIGH: frozenset({"начальный", "средний", "продвинутый"}),
}

TIME_BASED_IDS = frozenset({
    "plank", "long-lever-plank", "bear-plank", "hollow-hold", "side-plank",
    "side-plank-hip-dip", "dead-hang", "towel-hang", "copenhagen-plank",
    "deep-squat-hold",
})


def _scheduled_weekdays(level: ActivityLevel) -> set[int]:
    return set(BLUEPRINTS[level])


def _available_equipment(profile: UserProfile) -> set[str]:
    # Bodyweight work remains available alongside any selected gear.
    return set(profile.workout_equipment or EQUIPMENT_TYPES) | {"вес тела", "без оборудования"}


def _candidates(muscle: str, level: ActivityLevel, available_equipment: set[str]) -> list[Exercise]:
    candidates = [
        exercise for exercise in EXERCISES
        if exercise.primary_muscle == muscle
        and exercise.equipment in available_equipment
        and exercise.difficulty in DIFFICULTIES[level]
    ]
    # Small stabiliser groups sometimes only have an intermediate variation. It is
    # better to provide an explicit, labelled option than silently omit the muscle.
    return candidates or [
        exercise for exercise in EXERCISES
        if exercise.primary_muscle == muscle and exercise.equipment in available_equipment
    ]


def _rotated_choice(candidates: list[Exercise], day: date, offset: int) -> Exercise:
    ordered = sorted(candidates, key=lambda item: item.id)
    return ordered[(day.toordinal() + offset * 7) % len(ordered)]


def _select_exercises(blueprint: WorkoutBlueprint, day: date, profile: UserProfile) -> list[Exercise]:
    strength_count = {ActivityLevel.LOW: 2, ActivityLevel.MEDIUM: 3, ActivityLevel.HIGH: 4}[
        profile.activity_level
    ]
    selected: list[Exercise] = []
    available_equipment = _available_equipment(profile)
    focus = tuple(dict.fromkeys([*profile.workout_focus_muscles, *blueprint.focus]))

    # A rotating mobility warm-up always comes from the registry too.
    selected.append(
        _rotated_choice(
            _candidates("мобильность", profile.activity_level, available_equipment), day, 0
        )
    )
    for offset, muscle in enumerate(focus[:strength_count], start=1):
        candidates = _candidates(muscle, profile.activity_level, available_equipment)
        if not candidates:
            continue
        exercise = _rotated_choice(candidates, day, offset)
        if exercise.id not in {item.id for item in selected}:
            selected.append(exercise)

    finisher_muscle = "кардио" if profile.goal is Goal.LOSE else "кор"
    finisher_candidates = _candidates(finisher_muscle, profile.activity_level, available_equipment)
    finisher = _rotated_choice(finisher_candidates, day, 8) if finisher_candidates else None
    if finisher is not None and finisher.id not in {item.id for item in selected}:
        selected.append(finisher)
    return selected


def _prescription(exercise: Exercise, level: ActivityLevel) -> tuple[int, int | None, int | None]:
    if exercise.modality == "mobility":
        return 1, None, {ActivityLevel.LOW: 180, ActivityLevel.MEDIUM: 150, ActivityLevel.HIGH: 120}[level]
    if exercise.modality == "cardio":
        return {ActivityLevel.LOW: 3, ActivityLevel.MEDIUM: 4, ActivityLevel.HIGH: 5}[level], None, {
            ActivityLevel.LOW: 60, ActivityLevel.MEDIUM: 75, ActivityLevel.HIGH: 90,
        }[level]
    if exercise.id in TIME_BASED_IDS:
        return {ActivityLevel.LOW: 2, ActivityLevel.MEDIUM: 3, ActivityLevel.HIGH: 4}[level], None, {
            ActivityLevel.LOW: 25, ActivityLevel.MEDIUM: 35, ActivityLevel.HIGH: 45,
        }[level]
    return {ActivityLevel.LOW: 2, ActivityLevel.MEDIUM: 3, ActivityLevel.HIGH: 4}[level], {
        ActivityLevel.LOW: 10, ActivityLevel.MEDIUM: 12, ActivityLevel.HIGH: 10,
    }[level], None


def _estimated_kcal(level: ActivityLevel, exercise_count: int) -> int:
    baseline = {ActivityLevel.LOW: 170, ActivityLevel.MEDIUM: 260, ActivityLevel.HIGH: 380}[level]
    return baseline + max(0, exercise_count - 4) * 15


async def ensure_workouts(
    session: AsyncSession,
    user_id: uuid.UUID,
    profile: UserProfile,
    date_from: date,
    date_to: date,
) -> None:
    # Two parallel reads (e.g. /today and /calendar on app start) would otherwise both
    # insert the same day and one would fail on the unique constraint.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"workouts:{user_id}"}
    )
    existing_days = set(
        (await session.scalars(
            select(Workout.day).where(
                Workout.user_id == user_id,
                Workout.day >= date_from,
                Workout.day <= date_to,
            )
        )).all()
    )
    level = profile.activity_level
    duration = {ActivityLevel.LOW: 30, ActivityLevel.MEDIUM: 40, ActivityLevel.HIGH: 50}[level]
    current = date_from
    while current <= date_to:
        blueprint = BLUEPRINTS[level].get(current.weekday())
        if blueprint is not None and current not in existing_days:
            exercises = _select_exercises(blueprint, current, profile)
            workout = Workout(
                user_id=user_id,
                day=current,
                title=blueprint.title,
                duration_minutes=duration,
                estimated_kcal=_estimated_kcal(level, len(exercises)),
            )
            session.add(workout)
            await session.flush()
            for position, exercise in enumerate(exercises, start=1):
                sets, reps, seconds = _prescription(exercise, level)
                session.add(
                    WorkoutExercise(
                        workout_id=workout.id,
                        catalog_id=exercise.id,
                        name=exercise.name,
                        sets=sets,
                        reps=reps,
                        duration_seconds=seconds,
                        position=position,
                    )
                )
        current += timedelta(days=1)
    await session.flush()
