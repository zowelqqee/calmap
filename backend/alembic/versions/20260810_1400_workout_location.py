"""Persist the onboarding workout location choice.

Revision ID: c4d91b7e2a10
Revises: a74e3f1b9c20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d91b7e2a10"
down_revision: Union[str, None] = "a74e3f1b9c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "workout_location",
            sa.String(length=32),
            server_default="home",
            nullable=False,
        ),
    )
    op.alter_column("user_profiles", "workout_location", server_default=None)


def downgrade() -> None:
    op.drop_column("user_profiles", "workout_location")
