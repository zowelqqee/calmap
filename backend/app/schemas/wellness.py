from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class ExerciseOut(BaseModel):
    id: uuid.UUID
    catalog_id: str | None
    name: str
    primary_muscle: str | None
    secondary_muscles: list[str]
    equipment: str | None
    sets: int
    reps: int | None
    duration_seconds: int | None
    position: int
    is_completed: bool
    is_skipped: bool


class ExerciseCatalogOut(BaseModel):
    id: str
    name: str
    primary_muscle: str
    secondary_muscles: list[str]
    equipment: str
    difficulty: str
    modality: str


class ExerciseRegistryMetaOut(BaseModel):
    total: int
    muscle_groups: list[str]
    equipment: list[str]


class WorkoutOut(BaseModel):
    id: uuid.UUID
    day: date
    title: str
    duration_minutes: int
    estimated_kcal: int
    body_sex: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    completed_count: int
    total_count: int
    exercises: list[ExerciseOut]


class ExerciseUpdate(BaseModel):
    is_completed: bool = False
    is_skipped: bool = False


class WorkoutPreferencesOut(BaseModel):
    location: str = "home"
    equipment: list[str]
    focus_muscles: list[str]


class WorkoutPreferencesUpdate(WorkoutPreferencesOut):
    rebuild_planned: bool = True


class WorkoutCalendarDayOut(BaseModel):
    id: uuid.UUID
    day: date
    title: str
    status: str
    duration_minutes: int


class ProgressEntryCreate(BaseModel):
    day: date
    weight_kg: float = Field(ge=30, le=300)
    waist_cm: float | None = Field(default=None, ge=30, le=250)
    note: str | None = Field(default=None, max_length=1000)


class ProgressEntryOut(ProgressEntryCreate):
    id: uuid.UUID


class ProgressOverviewOut(BaseModel):
    goal: str
    start_date: date
    end_date: date
    start_weight_kg: float
    current_weight_kg: float
    target_weight_kg: float
    progress_pct: float
    workouts_completed: int
    average_kcal: float
    entries: list[ProgressEntryOut]


class ProgressReportOut(BaseModel):
    generated_for: date
    summary: ProgressOverviewOut
    weight_change_kg: float
    waist_change_cm: float | None
    notice: str = "Отчёт носит информационный характер."
