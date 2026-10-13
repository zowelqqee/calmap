"""Store equipment and muscle-focus choices for workout generation.

Revision ID: a74e3f1b9c20
Revises: 6a1f2d0c9b38
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a74e3f1b9c20"
down_revision: Union[str, None] = "6a1f2d0c9b38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    default = sa.text("'[]'::jsonb")
    op.add_column(
        "user_profiles",
        sa.Column("workout_equipment", postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False),
    )
    op.add_column(
        "user_profiles",
        sa.Column("workout_focus_muscles", postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False),
    )
    op.alter_column("user_profiles", "workout_equipment", server_default=None)
    op.alter_column("user_profiles", "workout_focus_muscles", server_default=None)


def downgrade() -> None:
    op.drop_column("user_profiles", "workout_focus_muscles")
    op.drop_column("user_profiles", "workout_equipment")
