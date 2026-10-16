from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentProfile, CurrentUser, DbSession
from app.schemas.onboarding import TargetsOut
from app.services.planning import (
    current_targets,
    latest_weight,
    store_targets,
    targets_for_profile,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/targets", response_model=TargetsOut)
async def get_targets(user: CurrentUser, session: DbSession) -> TargetsOut:
    row = await current_targets(session, user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no targets computed yet")
    return TargetsOut(
        bmr_kcal=row.bmr_kcal,
        tdee_kcal=row.tdee_kcal,
        target_kcal=row.target_kcal,
        protein_g=row.protein_g,
        fat_g=row.fat_g,
        carbs_g=row.carbs_g,
        fiber_g=row.fiber_g,
        water_ml=row.water_ml,
        adjustments=row.adjustments,
    )


@router.post("/targets/recalculate", response_model=TargetsOut)
async def recalculate_targets(
    user: CurrentUser, profile: CurrentProfile, session: DbSession
) -> TargetsOut:
    """Recompute after a weight or goal change. The old row is kept, not overwritten —
    target history is what makes "why did my calories drop?" answerable."""
    computed = targets_for_profile(profile, weight_kg=await latest_weight(session, user.id))
    row = await store_targets(session, user.id, computed)
    return TargetsOut(
        bmr_kcal=row.bmr_kcal,
        tdee_kcal=row.tdee_kcal,
        target_kcal=row.target_kcal,
        protein_g=row.protein_g,
        fat_g=row.fat_g,
        carbs_g=row.carbs_g,
        fiber_g=row.fiber_g,
        water_ml=row.water_ml,
        adjustments=row.adjustments,
    )
