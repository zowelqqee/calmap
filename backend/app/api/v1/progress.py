from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentProfile, CurrentUser, DbSession
from app.db.models import DiaryEntry, ProgressEntry, Workout
from app.schemas.wellness import (
    ProgressEntryCreate, ProgressEntryOut, ProgressOverviewOut, ProgressReportOut,
)

router = APIRouter(prefix="/progress", tags=["progress"])


def _entry(row: ProgressEntry) -> ProgressEntryOut:
    return ProgressEntryOut(
        id=row.id, day=row.day, weight_kg=row.weight_kg,
        waist_cm=row.waist_cm, note=row.note,
    )


async def _overview(user, profile, session: DbSession) -> ProgressOverviewOut:
    entries = (await session.scalars(
        select(ProgressEntry).where(ProgressEntry.user_id == user.id).order_by(ProgressEntry.day)
    )).all()
    start_weight = profile.weight_kg
    current_weight = entries[-1].weight_kg if entries else profile.weight_kg
    target_weight = profile.target_weight_kg or profile.weight_kg
    total_delta = target_weight - start_weight
    progress = 0.0 if abs(total_delta) < 0.01 else (current_weight - start_weight) / total_delta * 100
    completed = await session.scalar(
        select(func.count()).select_from(Workout).where(
            Workout.user_id == user.id, Workout.status == "completed"
        )
    ) or 0
    since = date.today() - timedelta(days=6)
    daily = (await session.execute(
        select(DiaryEntry.day, func.sum(DiaryEntry.kcal)).where(
            DiaryEntry.user_id == user.id, DiaryEntry.day >= since
        ).group_by(DiaryEntry.day)
    )).all()
    average_kcal = sum(float(total) for _, total in daily) / len(daily) if daily else 0.0
    return ProgressOverviewOut(
        goal=profile.goal.value,
        start_date=profile.program_started_on or date.today(),
        end_date=profile.program_ends_on or date.today() + timedelta(weeks=12),
        start_weight_kg=start_weight,
        current_weight_kg=current_weight,
        target_weight_kg=target_weight,
        progress_pct=round(max(0.0, min(100.0, progress)), 1),
        workouts_completed=int(completed),
        average_kcal=round(average_kcal, 1),
        entries=[_entry(row) for row in entries],
    )


@router.get("/overview", response_model=ProgressOverviewOut)
async def overview(user: CurrentUser, profile: CurrentProfile, session: DbSession) -> ProgressOverviewOut:
    return await _overview(user, profile, session)


@router.get("/entries", response_model=list[ProgressEntryOut])
async def entries(user: CurrentUser, session: DbSession) -> list[ProgressEntryOut]:
    rows = (await session.scalars(
        select(ProgressEntry).where(ProgressEntry.user_id == user.id).order_by(ProgressEntry.day.desc())
    )).all()
    return [_entry(row) for row in rows]


@router.post("/entries", response_model=ProgressEntryOut, status_code=status.HTTP_201_CREATED)
async def add_entry(
    payload: ProgressEntryCreate, user: CurrentUser, session: DbSession
) -> ProgressEntryOut:
    row = await session.scalar(select(ProgressEntry).where(
        ProgressEntry.user_id == user.id, ProgressEntry.day == payload.day
    ))
    if row is None:
        row = ProgressEntry(user_id=user.id, day=payload.day, weight_kg=payload.weight_kg)
        session.add(row)
    row.weight_kg = payload.weight_kg
    row.waist_cm = payload.waist_cm
    row.note = payload.note
    await session.flush()
    return _entry(row)


@router.delete("/entries/{entry_id}", response_model=dict)
async def delete_entry(entry_id: str, user: CurrentUser, session: DbSession) -> dict:
    try:
        import uuid
        key = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found") from None
    row = await session.get(ProgressEntry, key)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    await session.delete(row)
    return {"deleted": True}


@router.get("/report", response_model=ProgressReportOut)
async def report(user: CurrentUser, profile: CurrentProfile, session: DbSession) -> ProgressReportOut:
    summary = await _overview(user, profile, session)
    waist_values = [entry.waist_cm for entry in summary.entries if entry.waist_cm is not None]
    waist_change = waist_values[-1] - waist_values[0] if len(waist_values) >= 2 else None
    return ProgressReportOut(
        generated_for=date.today(), summary=summary,
        weight_change_kg=round(summary.current_weight_kg - summary.start_weight_kg, 1),
        waist_change_cm=round(waist_change, 1) if waist_change is not None else None,
    )
