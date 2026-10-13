from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.domain.exercises import EQUIPMENT_TYPES, EXERCISES, MUSCLE_GROUPS, Exercise
from app.schemas.wellness import ExerciseCatalogOut, ExerciseRegistryMetaOut

router = APIRouter(prefix="/exercises", tags=["exercises"])


def _out(exercise: Exercise) -> ExerciseCatalogOut:
    return ExerciseCatalogOut(
        id=exercise.id,
        name=exercise.name,
        primary_muscle=exercise.primary_muscle,
        secondary_muscles=list(exercise.secondary_muscles),
        equipment=exercise.equipment,
        difficulty=exercise.difficulty,
        modality=exercise.modality,
    )


@router.get("", response_model=list[ExerciseCatalogOut])
async def list_exercises(
    user: CurrentUser,
    muscle: str | None = None,
    equipment: str | None = None,
    difficulty: str | None = Query(default=None, pattern="^(начальный|средний|продвинутый)$"),
    modality: str | None = Query(default=None, pattern="^(strength|cardio|mobility)$"),
    q: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=100, ge=1, le=300),
) -> list[ExerciseCatalogOut]:
    """Search the exercise registry by target muscle, gear, difficulty or name."""
    del user  # The registry is shared, but remains inside the authenticated API surface.
    query = q.lower() if q else None
    rows = [
        exercise for exercise in EXERCISES
        if (muscle is None or exercise.primary_muscle == muscle)
        and (equipment is None or exercise.equipment == equipment)
        and (difficulty is None or exercise.difficulty == difficulty)
        and (modality is None or exercise.modality == modality)
        and (query is None or query in exercise.name.lower() or query in exercise.id)
    ]
    return [_out(exercise) for exercise in rows[:limit]]


@router.get("/meta", response_model=ExerciseRegistryMetaOut)
async def exercise_registry_meta(user: CurrentUser) -> ExerciseRegistryMetaOut:
    del user
    return ExerciseRegistryMetaOut(
        total=len(EXERCISES), muscle_groups=list(MUSCLE_GROUPS), equipment=list(EQUIPMENT_TYPES)
    )
