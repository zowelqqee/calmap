"""Consent records and the destruction log (152-FZ evidence).

Revision ID: e3a8c5d1f720
Revises: d7e2f1a9b350
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e3a8c5d1f720"
down_revision: Union[str, None] = "d7e2f1a9b350"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "user_consents",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("document", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("ip_address", sa.String(length=45)),
        sa.Column("user_agent", sa.String(length=255)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        *_base_columns(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_consents_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_consents"),
    )
    op.create_index("ix_user_consents_user_id", "user_consents", ["user_id"])

    op.create_table(
        "account_deletions",
        sa.Column("user_ref", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_account_deletions"),
    )
    op.create_index("ix_account_deletions_user_ref", "account_deletions", ["user_ref"])


def downgrade() -> None:
    op.drop_index("ix_account_deletions_user_ref", table_name="account_deletions")
    op.drop_table("account_deletions")
    op.drop_index("ix_user_consents_user_id", table_name="user_consents")
    op.drop_table("user_consents")
