"""Add a stable registry ID to workout exercise instances.

Revision ID: 6a1f2d0c9b38
Revises: e56f0c8d71aa
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a1f2d0c9b38"
down_revision: Union[str, None] = "e56f0c8d71aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workout_exercises", sa.Column("catalog_id", sa.String(length=100), nullable=True))
    op.create_index("ix_workout_exercises_catalog_id", "workout_exercises", ["catalog_id"])


def downgrade() -> None:
    op.drop_index("ix_workout_exercises_catalog_id", table_name="workout_exercises")
    op.drop_column("workout_exercises", "catalog_id")
