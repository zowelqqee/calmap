from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlalchemy import func, select, text

from app.api.deps import CurrentSubscription, CurrentUser, DbSession
from app.db.models import DiaryEntry, Product, VisionRecognition
from app.schemas.tracking import (
    VisionCandidateOut,
    VisionConfirmRequest,
    VisionRecognizeOut,
)
from app.services.vision import CatalogHint, get_vision_provider

router = APIRouter(prefix="/vision", tags=["vision"])
logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic"}


@router.post("/recognize", response_model=VisionRecognizeOut)
async def recognize(
    user: CurrentUser,
    subscription: CurrentSubscription,
    session: DbSession,
    image: UploadFile = File(...),
) -> VisionRecognizeOut:
    if image.content_type not in ALLOWED_MIME:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported image type")

    # Read at most one byte past the limit so an oversized upload is never buffered
    # in full.
    payload = await image.read(MAX_IMAGE_BYTES + 1)
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "image too large")

    # --- dedupe first: re-sending the same photo costs nothing, so it must not count
    # against the quota either. Checking the quota first would make a flaky upload
    # retry burn a free-tier user's only photo of the day.
    image_hash = hashlib.sha256(payload).hexdigest()
    cached = await session.scalar(
        select(VisionRecognition)
        .where(
            VisionRecognition.user_id == user.id,
            VisionRecognition.image_hash == image_hash,
            VisionRecognition.created_at >= func.now() - timedelta(days=1),
        )
        .order_by(VisionRecognition.created_at.desc())
        .limit(1)
    )
    if cached is not None:
        return VisionRecognizeOut(
            recognition_id=cached.id,
            provider=cached.provider,
            model=cached.model,
            latency_ms=cached.latency_ms,
            candidates=[VisionCandidateOut(**c) for c in cached.candidates],
        )

    # --- per-tier quota: this is what keeps vision spend below subscription revenue ---
    # Serialise this user's recognitions so parallel uploads cannot all pass the
    # count before any of them is recorded. Released at transaction end.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"vision:{user.id}"}
    )
    limit = subscription.limits["vision_per_day"]
    used = await session.scalar(
        select(func.count())
        .select_from(VisionRecognition)
        .where(
            VisionRecognition.user_id == user.id,
            VisionRecognition.created_at >= date.today(),
        )
    )
    if used is not None and used >= limit:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"daily photo limit reached for the '{subscription.tier}' plan ({limit}/day)",
        )

    # Keep the large external food dump out of the vision prompt. The curated
    # catalogue is the closed vocabulary used for photo recognition.
    products = (
        await session.scalars(
            select(Product).where(
                Product.is_active.is_(True),
                Product.source == "curated",
            )
        )
    ).all()
    by_slug = {p.slug: p for p in products}
    catalog = [CatalogHint(slug=p.slug, name=p.name) for p in products]

    provider = get_vision_provider()
    try:
        result = await provider.recognize(payload, image.content_type, catalog)
    except (RuntimeError, OSError, httpx.HTTPError):
        # Provider errors can carry request URLs and headers; log them, never return them.
        logger.exception("vision provider %s failed", provider.name)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "photo recognition is temporarily unavailable"
        ) from None

    candidates: list[VisionCandidateOut] = []
    for raw in result.candidates:
        product = by_slug.get(raw.slug)
        if product is None:
            continue
        factor = raw.grams / 100.0
        candidates.append(
            VisionCandidateOut(
                product_id=product.id,
                product_slug=product.slug,
                name=product.name,
                grams_estimate=raw.grams,
                confidence=raw.confidence,
                # Nutrition is computed here, never taken from the model.
                kcal=round(product.kcal_per_100g * factor, 1),
                protein_g=round(product.protein_per_100g * factor, 1),
                fat_g=round(product.fat_per_100g * factor, 1),
                carbs_g=round(product.carbs_per_100g * factor, 1),
                alternatives=[by_slug[a].name for a in raw.alternatives if a in by_slug],
            )
        )

    recognition = VisionRecognition(
        user_id=user.id,
        image_hash=image_hash,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        raw_response=result.raw_response,
        candidates=[c.model_dump(mode="json") for c in candidates],
    )
    session.add(recognition)
    await session.flush()

    return VisionRecognizeOut(
        recognition_id=recognition.id,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        candidates=candidates,
    )


@router.post("/{recognition_id}/confirm", status_code=status.HTTP_201_CREATED)
async def confirm(
    recognition_id: uuid.UUID,
    payload: VisionConfirmRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    """Write the user's corrected version to the diary.

    The gap between `candidates` and `confirmed_items` is the only ground truth this
    product will ever get about recognition accuracy, so both are stored — it is the
    dataset for prompt calibration and the source of the "share of estimates the user
    edited" metric.
    """
    recognition = await session.get(VisionRecognition, recognition_id)
    if recognition is None or recognition.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recognition not found")
    if not payload.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no items confirmed")

    from app.api.v1.diary import build_entry

    created: list[DiaryEntry] = []
    for item in payload.items:
        product = await session.get(Product, item.product_id)
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"product {item.product_id} not found")
        entry = await build_entry(
            session,
            user.id,
            payload.day,
            payload.meal_type,
            item.grams,
            product=product,
            source="vision",
        )
        session.add(entry)
        created.append(entry)

    proposed = {
        (c.get("product_slug"), round(float(c.get("grams_estimate", 0))))
        for c in recognition.candidates
    }
    confirmed = {(e.name, round(e.grams)) for e in created}
    recognition.confirmed_items = [
        {"product_id": str(i.product_id), "grams": i.grams} for i in payload.items
    ]
    recognition.was_edited = len(proposed) != len(confirmed) or any(
        round(float(c.get("grams_estimate", 0))) != round(i.grams)
        for c, i in zip(recognition.candidates, payload.items)
    )
    await session.flush()

    return {
        "recognition_id": recognition.id,
        "entries_created": len(created),
        "was_edited": recognition.was_edited,
    }
