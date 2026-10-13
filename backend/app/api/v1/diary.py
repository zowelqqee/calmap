from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.db.models import DiaryEntry, Product, Recipe
from app.schemas.tracking import (
    DiaryEntryCreate,
    DiaryEntryOut,
    DiarySummaryOut,
    RepeatMealRequest,
)
from app.services.planning import current_targets

router = APIRouter(prefix="/diary", tags=["diary"])


def _out(entry: DiaryEntry) -> DiaryEntryOut:
    return DiaryEntryOut(
        id=entry.id,
        day=entry.day,
        meal_type=entry.meal_type,
        name=entry.name,
        grams=entry.grams,
        kcal=entry.kcal,
        protein_g=entry.protein_g,
        fat_g=entry.fat_g,
        carbs_g=entry.carbs_g,
        source=entry.source,
    )


async def build_entry(
    session: DbSession,
    user_id: uuid.UUID,
    day: date,
    meal_type,
    grams: float,
    *,
    product: Product | None = None,
    recipe: Recipe | None = None,
    source: str = "manual",
) -> DiaryEntry:
    """Snapshot nutrition at log time.

    Copying the numbers rather than joining them at read time means a later catalogue
    correction cannot silently rewrite history — which matters for a user tracking a cut
    over months.
    """
    factor = grams / 100.0
    if product is not None:
        return DiaryEntry(
            user_id=user_id,
            day=day,
            meal_type=meal_type,
            product_id=product.id,
            name=product.name,
            grams=grams,
            kcal=round(product.kcal_per_100g * factor, 1),
            protein_g=round(product.protein_per_100g * factor, 1),
            fat_g=round(product.fat_per_100g * factor, 1),
            carbs_g=round(product.carbs_per_100g * factor, 1),
            source=source,
        )
    assert recipe is not None
    return DiaryEntry(
        user_id=user_id,
        day=day,
        meal_type=meal_type,
        recipe_id=recipe.id,
        name=recipe.name,
        grams=grams,
        kcal=round(recipe.kcal_per_100g * factor, 1),
        protein_g=round(recipe.protein_per_100g * factor, 1),
        fat_g=round(recipe.fat_per_100g * factor, 1),
        carbs_g=round(recipe.carbs_per_100g * factor, 1),
        source=source,
    )


@router.post("/entries", response_model=DiaryEntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(
    payload: DiaryEntryCreate, user: CurrentUser, session: DbSession
) -> DiaryEntryOut:
    product = recipe = None
    if payload.product_id:
        product = await session.get(Product, payload.product_id)
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "product not found")
    elif payload.recipe_id:
        recipe = await session.get(Recipe, payload.recipe_id)
        if recipe is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")

    if product is not None or recipe is not None:
        entry = await build_entry(
            session,
            user.id,
            payload.day,
            payload.meal_type,
            payload.grams,
            product=product,
            recipe=recipe,
            source=payload.source,
        )
    else:
        entry = DiaryEntry(
            user_id=user.id,
            day=payload.day,
            meal_type=payload.meal_type,
            name=payload.name or "Ручная запись",
            grams=payload.grams,
            kcal=payload.kcal or 0,
            protein_g=payload.protein_g,
            fat_g=payload.fat_g,
            carbs_g=payload.carbs_g,
            source=payload.source,
        )
    session.add(entry)
    await session.flush()
    return _out(entry)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: uuid.UUID, user: CurrentUser, session: DbSession) -> None:
    entry = await session.get(DiaryEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    await session.delete(entry)


@router.get("/{day}", response_model=DiarySummaryOut)
async def day_summary(day: date, user: CurrentUser, session: DbSession) -> DiarySummaryOut:
    entries = (
        await session.scalars(
            select(DiaryEntry)
            .where(DiaryEntry.user_id == user.id, DiaryEntry.day == day)
            .order_by(DiaryEntry.created_at)
        )
    ).all()
    targets = await current_targets(session, user.id)
    return DiarySummaryOut(
        day=day,
        kcal=round(sum(e.kcal for e in entries), 1),
        protein_g=round(sum(e.protein_g for e in entries), 1),
        fat_g=round(sum(e.fat_g for e in entries), 1),
        carbs_g=round(sum(e.carbs_g for e in entries), 1),
        target_kcal=targets.target_kcal if targets else None,
        target_protein_g=targets.protein_g if targets else None,
        target_fat_g=targets.fat_g if targets else None,
        target_carbs_g=targets.carbs_g if targets else None,
        entries=[_out(e) for e in entries],
    )


@router.post("/repeat", response_model=list[DiaryEntryOut])
async def repeat_meal(
    payload: RepeatMealRequest, user: CurrentUser, session: DbSession
) -> list[DiaryEntryOut]:
    """Copy a whole meal from another day.

    Cheap in every sense: no model call, no search, one tap. For regular users this
    replaces a large share of photo recognitions, which is the main lever on vision
    cost per active user.
    """
    source = (
        await session.scalars(
            select(DiaryEntry).where(
                DiaryEntry.user_id == user.id,
                DiaryEntry.day == payload.source_day,
                DiaryEntry.meal_type == payload.meal_type,
            )
        )
    ).all()
    if not source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "nothing logged for that meal")

    copies = []
    for entry in source:
        copy = DiaryEntry(
            user_id=user.id,
            day=payload.target_day,
            meal_type=entry.meal_type,
            product_id=entry.product_id,
            recipe_id=entry.recipe_id,
            name=entry.name,
            grams=entry.grams,
            kcal=entry.kcal,
            protein_g=entry.protein_g,
            fat_g=entry.fat_g,
            carbs_g=entry.carbs_g,
            source="repeat",
        )
        session.add(copy)
        copies.append(copy)
    await session.flush()
    return [_out(c) for c in copies]
