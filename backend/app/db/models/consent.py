"""Evidence for 152-FZ: consents given by users and destruction of their data.

The operator must be able to prove that consent was obtained (art. 9 part 3) and
to confirm destruction of personal data (art. 21, Roskomnadzor order No. 179).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class UserConsent(Base, UUIDPrimaryKey, Timestamped):
    """One consent act: which document, which version, when and from where."""

    __tablename__ = "user_consents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    #: personal_data | health_data | ai_assistant
    document: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountDeletion(Base, UUIDPrimaryKey, Timestamped):
    """Destruction log entry. Kept after the account is gone, so it holds only the
    former account id (no contact data) and what was destroyed."""

    __tablename__ = "account_deletions"

    user_ref: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
