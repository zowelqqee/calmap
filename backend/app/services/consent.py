"""Consent acts required by 152-FZ.

* personal_data — at registration; a separate document since 1 September 2025
  (art. 9 part 1 as amended by 156-FZ).
* health_data — before the questionnaire collects body and diet data (special
  category, art. 10).
* ai_assistant — before the first AI consultation, whose provider may be abroad
  (cross-border transfer, art. 12).
* photo_recognition — before the first photo goes to the recognition provider,
  which may be abroad (art. 12).

Each act is stored with the document version, time, IP address and user agent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserConsent

#: Document → (current version, public page under /legal/).
CONSENT_DOCUMENTS: dict[str, tuple[str, str]] = {
    "personal_data": ("2026-10-14", "consent"),
    "health_data": ("2026-10-14", "health-consent"),
    "ai_assistant": ("2026-10-14", "ai-consent"),
    "photo_recognition": ("2026-10-15", "photo-consent"),
}

#: Withdrawing these ends all processing, i.e. the account itself (art. 9 part 5).
ACCOUNT_LEVEL_CONSENTS = {"personal_data", "health_data"}

REQUIRED_MESSAGES = {
    "personal_data": "Для регистрации нужно согласие на обработку персональных данных.",
    "health_data": "Подтвердите согласие на обработку данных о здоровье.",
    "ai_assistant": "Подтвердите согласие на передачу данных AI-консультанту.",
    "photo_recognition": "Подтвердите согласие на передачу фото сервису распознавания.",
}


async def record_consent(
    session: AsyncSession, user_id: uuid.UUID, document: str, request: Request | None
) -> UserConsent:
    version, _page = CONSENT_DOCUMENTS[document]
    consent = UserConsent(
        user_id=user_id,
        document=document,
        version=version,
        ip_address=request.client.host if request and request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:255] if request else None,
    )
    session.add(consent)
    await session.flush()
    return consent


async def active_consents(session: AsyncSession, user_id: uuid.UUID) -> dict[str, UserConsent]:
    rows = (
        await session.scalars(
            select(UserConsent)
            .where(UserConsent.user_id == user_id, UserConsent.withdrawn_at.is_(None))
            .order_by(UserConsent.created_at)
        )
    ).all()
    return {row.document: row for row in rows}


async def require_consent(session: AsyncSession, user_id: uuid.UUID, document: str) -> None:
    if document not in await active_consents(session, user_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "consent_required",
                "document": document,
                "message": REQUIRED_MESSAGES[document],
            },
        )


async def withdraw_consent(session: AsyncSession, user_id: uuid.UUID, document: str) -> bool:
    rows = (
        await session.scalars(
            select(UserConsent).where(
                UserConsent.user_id == user_id,
                UserConsent.document == document,
                UserConsent.withdrawn_at.is_(None),
            )
        )
    ).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.withdrawn_at = now
    await session.flush()
    return bool(rows)
