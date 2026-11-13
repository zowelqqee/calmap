"""Consents the user has given, and giving or withdrawing them."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.services.consent import (
    ACCOUNT_LEVEL_CONSENTS,
    CONSENT_DOCUMENTS,
    active_consents,
    record_consent,
    withdraw_consent,
)

router = APIRouter(prefix="/me/consents", tags=["consents"])

ConsentDocument = Literal["personal_data", "health_data", "ai_assistant", "photo_recognition"]


class ConsentIn(BaseModel):
    document: ConsentDocument


class ConsentOut(BaseModel):
    document: str
    version: str
    current_version: str
    given_at: datetime
    #: Public text at /legal/<page>
    page: str


def _out(document: str, version: str, given_at: datetime) -> ConsentOut:
    current, page = CONSENT_DOCUMENTS[document]
    return ConsentOut(
        document=document,
        version=version,
        current_version=current,
        given_at=given_at,
        page=page,
    )


@router.get("", response_model=list[ConsentOut])
async def list_consents(user: CurrentUser, session: DbSession) -> list[ConsentOut]:
    consents = await active_consents(session, user.id)
    return [_out(doc, row.version, row.created_at) for doc, row in consents.items()]


@router.post("", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def give_consent(
    payload: ConsentIn, request: Request, user: CurrentUser, session: DbSession
) -> ConsentOut:
    row = await record_consent(session, user.id, payload.document, request)
    return _out(row.document, row.version, row.created_at)


@router.delete("/{document}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_consent(document: ConsentDocument, user: CurrentUser, session: DbSession) -> None:
    if document in ACCOUNT_LEVEL_CONSENTS:
        # Without this consent nothing may be processed, so withdrawal is account
        # deletion — done explicitly through DELETE /v1/auth/me.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Отзыв этого согласия означает удаление аккаунта: Профиль → Удалить аккаунт.",
        )
    await withdraw_consent(session, user.id, document)
