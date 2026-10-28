"""Sign-in codes record how they were delivered: SMS or the Telegram bot.

Revision ID: d7a1f3c9e520
Revises: c2e5a8d4f193
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7a1f3c9e520"
down_revision: Union[str, None] = "c2e5a8d4f193"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "phone_codes",
        sa.Column("channel", sa.String(length=16), server_default="sms", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("phone_codes", "channel")
