from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from app.api.deps import CurrentProfile, CurrentUser, DbSession
from app.db.models import Workout, WorkoutExercise
from app.domain.enums import WorkoutLocation
from app.domain.exercises import EQUIPMENT_TYPES, EXERCISE_BY_ID, MUSCLE_GROUPS
from app.schemas.wellness import (
    ExerciseOut, ExerciseUpdate, WorkoutCalendarDayOut, WorkoutOut,
    WorkoutPreferencesOut, WorkoutPreferencesUpdate,
)
from app.services.workouts import ensure_workouts

router = APIRouter(prefix="/workouts", tags=["workouts"])


def _out(workout: Workout, body_sex: str) -> WorkoutOut:
    exercises = []
    for exercise in workout.exercises:
        catalogue_entry = EXERCISE_BY_ID.get(exercise.catalog_id or "")
        exercises.append(
            ExerciseOut(
                id=exercise.id,
                catalog_id=exercise.catalog_id,
                name=exercise.name,
                primary_muscle=catalogue_entry.primary_muscle if catalogue_entry else None,
                secondary_muscles=list(catalogue_entry.secondary_muscles) if catalogue_entry else [],
                equipment=catalogue_entry.equipment if catalogue_entry else None,
                sets=exercise.sets,
                reps=exercise.reps,
                duration_seconds=exercise.duration_seconds,
                position=exercise.position,
                is_completed=exercise.is_completed,
                is_skipped=exercise.is_skipped,
            )
        )
    return WorkoutOut(
        id=workout.id, day=workout.day, title=workout.title,
        duration_minutes=workout.duration_minutes,
        body_sex=body_sex,
        estimated_kcal=workout.estimated_kcal, status=workout.status,
        started_at=workout.started_at, completed_at=workout.completed_at,
        completed_count=sum(e.is_completed for e in workout.exercises),
        total_count=len(workout.exercises), exercises=exercises,
    )


async def _owned(session: DbSession, workout_id: uuid.UUID, user_id: uuid.UUID) -> Workout:
    workout = await session.get(Workout, workout_id)
    if workout is None or workout.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workout not found")
    return workout


@router.get("/preferences", response_model=WorkoutPreferencesOut)
async def workout_preferences(profile: CurrentProfile) -> WorkoutPreferencesOut:
    return WorkoutPreferencesOut(
        location=profile.workout_location.value,
        equipment=list(profile.workout_equipment), focus_muscles=list(profile.workout_focus_muscles)
    )


@router.patch("/preferences", response_model=WorkoutPreferencesOut)
async def update_workout_preferences(
    payload: WorkoutPreferencesUpdate,
    user: CurrentUser,
    profile: CurrentProfile,
    session: DbSession,
) -> WorkoutPreferencesOut:
    unknown_equipment = set(payload.equipment) - set(EQUIPMENT_TYPES)
    unknown_muscles = set(payload.focus_muscles) - set(MUSCLE_GROUPS)
    if unknown_equipment or unknown_muscles:
        invalid = sorted(unknown_equipment | unknown_muscles)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown workout preferences: {invalid}")
    profile.workout_equipment = sorted(set(payload.equipment))
    profile.workout_focus_muscles = sorted(set(payload.focus_muscles))
    if payload.rebuild_planned:
        await session.execute(
            delete(Workout).where(
                Workout.user_id == user.id,
                Workout.status == "planned",
                Workout.day >= date.today(),
            )
        )
    await session.flush()
    return WorkoutPreferencesOut(
        location=profile.workout_location.value,
        equipment=list(profile.workout_equipment), focus_muscles=list(profile.workout_focus_muscles)
    )


@router.get("/today", response_model=WorkoutOut | None)
async def today_workout(
    user: CurrentUser, profile: CurrentProfile, session: DbSession, day: date | None = None
) -> WorkoutOut | None:
    requested = day or date.today()
    await ensure_workouts(session, user.id, profile, requested, requested)
    workout = await session.scalar(
        select(Workout).where(Workout.user_id == user.id, Workout.day == requested)
    )
    return _out(workout, profile.sex.value) if workout else None


@router.get("/calendar", response_model=list[WorkoutCalendarDayOut])
async def workout_calendar(
    date_from: date, date_to: date, user: CurrentUser,
    profile: CurrentProfile, session: DbSession,
) -> list[WorkoutCalendarDayOut]:
    if (date_to - date_from).days > 62:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "range is limited to 63 days")
    await ensure_workouts(session, user.id, profile, date_from, date_to)
    rows = (await session.scalars(
        select(Workout).where(
            Workout.user_id == user.id, Workout.day >= date_from, Workout.day <= date_to
        ).order_by(Workout.day)
    )).all()
    return [WorkoutCalendarDayOut(
        id=w.id, day=w.day, title=w.title, status=w.status,
        duration_minutes=w.duration_minutes,
    ) for w in rows]


@router.get("/{workout_id}", response_model=WorkoutOut)
async def get_workout(
    workout_id: uuid.UUID, user: CurrentUser, profile: CurrentProfile, session: DbSession
) -> WorkoutOut:
    return _out(await _owned(session, workout_id, user.id), profile.sex.value)


@router.post("/{workout_id}/start", response_model=WorkoutOut)
async def start_workout(
    workout_id: uuid.UUID, user: CurrentUser, profile: CurrentProfile, session: DbSession
) -> WorkoutOut:
    workout = await _owned(session, workout_id, user.id)
    if workout.status != "completed":
        workout.status = "in_progress"
        workout.started_at = workout.started_at or datetime.now(timezone.utc)
    await session.flush()
    return _out(workout, profile.sex.value)


@router.patch("/{workout_id}/exercises/{exercise_id}", response_model=WorkoutOut)
async def update_exercise(
    workout_id: uuid.UUID, exercise_id: uuid.UUID, payload: ExerciseUpdate,
    user: CurrentUser, profile: CurrentProfile, session: DbSession,
) -> WorkoutOut:
    workout = await _owned(session, workout_id, user.id)
    exercise = await session.get(WorkoutExercise, exercise_id)
    if exercise is None or exercise.workout_id != workout.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "exercise not found")
    exercise.is_completed = payload.is_completed
    exercise.is_skipped = payload.is_skipped
    if workout.status == "planned":
        workout.status = "in_progress"
        workout.started_at = datetime.now(timezone.utc)
    await session.flush()
    return _out(workout, profile.sex.value)


@router.post("/{workout_id}/complete", response_model=WorkoutOut)
async def complete_workout(
    workout_id: uuid.UUID, user: CurrentUser, profile: CurrentProfile, session: DbSession
) -> WorkoutOut:
    workout = await _owned(session, workout_id, user.id)
    workout.status = "completed"
    workout.started_at = workout.started_at or datetime.now(timezone.utc)
    workout.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return _out(workout, profile.sex.value)
