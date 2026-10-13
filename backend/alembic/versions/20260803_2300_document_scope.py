"""dashboard, recipes, workouts and progress

Revision ID: e56f0c8d71aa
Revises: 9a4d9f4b6c01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e56f0c8d71aa"
down_revision: Union[str, None] = "9a4d9f4b6c01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    op.add_column("user_profiles", sa.Column("program_started_on", sa.Date(), nullable=True))
    op.add_column("user_profiles", sa.Column("program_ends_on", sa.Date(), nullable=True))
    op.add_column("recipes", sa.Column("image_url", sa.String(length=500), nullable=True))
    op.add_column(
        "recipes",
        sa.Column("difficulty", sa.String(length=16), server_default="easy", nullable=False),
    )
    op.add_column(
        "recipes",
        sa.Column(
            "instructions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )

    op.create_table(
        "favorite_recipes",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("recipe_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "recipe_id", name="favorite_user_recipe"),
    )
    op.create_index("ix_favorite_recipes_user_id", "favorite_recipes", ["user_id"])
    op.create_index("ix_favorite_recipes_recipe_id", "favorite_recipes", ["recipe_id"])

    op.create_table(
        "workouts",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("estimated_kcal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "day", name="workout_user_day"),
    )
    op.create_index("ix_workouts_user_id", "workouts", ["user_id"])
    op.create_index("ix_workouts_day", "workouts", ["day"])

    op.create_table(
        "workout_exercises",
        sa.Column("workout_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("sets", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.Column("is_skipped", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["workout_id"], ["workouts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workout_exercises_workout_id", "workout_exercises", ["workout_id"])

    op.create_table(
        "progress_entries",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("waist_cm", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "day", name="progress_user_day"),
    )
    op.create_index("ix_progress_entries_user_id", "progress_entries", ["user_id"])
    op.create_index("ix_progress_entries_day", "progress_entries", ["day"])


def downgrade() -> None:
    op.drop_index("ix_progress_entries_day", table_name="progress_entries")
    op.drop_index("ix_progress_entries_user_id", table_name="progress_entries")
    op.drop_table("progress_entries")
    op.drop_index("ix_workout_exercises_workout_id", table_name="workout_exercises")
    op.drop_table("workout_exercises")
    op.drop_index("ix_workouts_day", table_name="workouts")
    op.drop_index("ix_workouts_user_id", table_name="workouts")
    op.drop_table("workouts")
    op.drop_index("ix_favorite_recipes_recipe_id", table_name="favorite_recipes")
    op.drop_index("ix_favorite_recipes_user_id", table_name="favorite_recipes")
    op.drop_table("favorite_recipes")
    op.drop_column("recipes", "instructions")
    op.drop_column("recipes", "difficulty")
    op.drop_column("recipes", "image_url")
    op.drop_column("user_profiles", "program_ends_on")
    op.drop_column("user_profiles", "program_started_on")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "name")
