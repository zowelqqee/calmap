from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AssistantChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=4000)


class AssistantMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class AssistantChatOut(BaseModel):
    conversation_id: uuid.UUID
    message: AssistantMessageOut
    provider: str
    model: str


class AssistantConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    messages: list[AssistantMessageOut]
