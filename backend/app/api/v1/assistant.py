from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select, text

from app.api.deps import CurrentProfile, CurrentSubscription, CurrentUser, DbSession
from app.db.models import AssistantConversation, AssistantMessage, DiaryEntry
from app.schemas.assistant import (
    AssistantChatOut,
    AssistantChatRequest,
    AssistantConversationOut,
    AssistantMessageOut,
)
from app.services.assistant import SYSTEM_PROMPT, get_assistant_provider
from app.services.planning import current_targets

router = APIRouter(prefix="/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)


def _message_out(message: AssistantMessage) -> AssistantMessageOut:
    return AssistantMessageOut(id=message.id, role=message.role, content=message.content, created_at=message.created_at)


async def _conversation(session: DbSession, user_id: uuid.UUID, conversation_id: uuid.UUID | None) -> AssistantConversation:
    if conversation_id is None:
        conversation = AssistantConversation(user_id=user_id, title=None)
        session.add(conversation)
        await session.flush()
        return conversation
    conversation = await session.scalar(
        select(AssistantConversation).where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conversation


async def _context(session: DbSession, user, profile) -> str:
    targets = await current_targets(session, user.id)
    entries = (
        await session.scalars(
            select(DiaryEntry)
            .where(DiaryEntry.user_id == user.id)
            .order_by(DiaryEntry.day.desc(), DiaryEntry.created_at.desc())
            .limit(30)
        )
    ).all()
    target_text = (
        f"цель {targets.target_kcal} ккал, Б {targets.protein_g} г, "
        f"Ж {targets.fat_g} г, У {targets.carbs_g} г"
        if targets else "цели ещё не рассчитаны"
    )
    diary_text = "; ".join(
        f"{entry.day} {entry.meal_type.value}: {entry.name} {entry.grams:g} г ({entry.kcal:g} ккал)"
        for entry in entries
    ) or "дневник пока пуст"
    return (
        f"Профиль: пол={profile.sex.value}, вес={profile.weight_kg:g} кг, "
        f"цель={profile.goal.value}, диета={profile.diet.value}, "
        f"аллергены={profile.allergens or 'нет'}, бюджет={profile.budget_amount or 'без лимита'} {profile.currency}. "
        f"Текущие цели: {target_text}. Последние записи: {diary_text}."
    )


@router.post("/chat", response_model=AssistantChatOut)
async def chat(
    payload: AssistantChatRequest,
    user: CurrentUser,
    profile: CurrentProfile,
    subscription: CurrentSubscription,
    session: DbSession,
) -> AssistantChatOut:
    limit = subscription.limits["assistant_messages_per_month"]
    if limit <= 0:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "AI consultation requires the pro plan")
    # Serialise this user's chat turns so parallel requests cannot all pass the quota.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"assistant:{user.id}"}
    )
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = await session.scalar(
        select(func.count())
        .select_from(AssistantMessage)
        .join(AssistantConversation, AssistantConversation.id == AssistantMessage.conversation_id)
        .where(
            AssistantConversation.user_id == user.id,
            AssistantMessage.role == "user",
            AssistantMessage.created_at >= month_start,
        )
    )
    if used is not None and used >= limit:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, f"monthly assistant limit reached ({limit})")

    conversation = await _conversation(session, user.id, payload.conversation_id)
    previous = (
        await session.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation.id)
            .order_by(AssistantMessage.created_at.desc())
            .limit(20)
        )
    ).all()
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + await _context(session, user, profile)}]
    messages.extend({"role": item.role, "content": item.content} for item in reversed(previous))
    messages.append({"role": "user", "content": payload.message})

    # Explicit timestamps: the column default is the transaction start time, which
    # would give the question and the reply the same created_at and an arbitrary order.
    user_message = AssistantMessage(
        conversation_id=conversation.id, role="user", content=payload.message, created_at=now
    )
    session.add(user_message)
    try:
        reply = await get_assistant_provider().reply(messages)
    except (RuntimeError, OSError, httpx.HTTPError):
        logger.exception("assistant provider failed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "AI consultation is temporarily unavailable"
        ) from None
    assistant_message = AssistantMessage(
        created_at=max(datetime.now(timezone.utc), now + timedelta(microseconds=1)),
        conversation_id=conversation.id,
        role="assistant",
        content=reply.content,
        provider=reply.provider,
        model=reply.model,
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
        raw_payload=reply.raw_payload,
    )
    if conversation.title is None:
        conversation.title = payload.message[:80]
    session.add(assistant_message)
    await session.flush()
    return AssistantChatOut(
        conversation_id=conversation.id,
        message=_message_out(assistant_message),
        provider=reply.provider,
        model=reply.model,
    )


@router.get("/conversations/{conversation_id}", response_model=AssistantConversationOut)
async def get_conversation(conversation_id: uuid.UUID, user: CurrentUser, session: DbSession) -> AssistantConversationOut:
    conversation = await _conversation(session, user.id, conversation_id)
    messages = (
        await session.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation.id)
            .order_by(AssistantMessage.created_at)
        )
    ).all()
    return AssistantConversationOut(id=conversation.id, title=conversation.title, messages=[_message_out(m) for m in messages])
