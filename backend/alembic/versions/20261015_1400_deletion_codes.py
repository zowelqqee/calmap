"""SMS codes get a purpose: sign-in or confirmation of account deletion.

Revision ID: c2e5a8d4f193
Revises: b8d3f6a1c472
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2e5a8d4f193"
down_revision: Union[str, None] = "b8d3f6a1c472"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "phone_codes",
        sa.Column("purpose", sa.String(length=16), server_default="sign_in", nullable=False),
    )


def downgrade() -> None:
    op.execute("DELETE FROM phone_codes WHERE purpose <> 'sign_in'")
    op.drop_column("phone_codes", "purpose")
