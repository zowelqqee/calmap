"""Sign-in by SMS code; Telegram is linked by phone instead of one-time codes.

Revision ID: f1b4d2e6a930
Revises: e3a8c5d1f720
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1b4d2e6a930"
down_revision: Union[str, None] = "e3a8c5d1f720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=16)))
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)

    op.create_table(
        "phone_codes",
        sa.Column("phone", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", sa.String(length=45)),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_phone_codes"),
    )
    op.create_index("ix_phone_codes_phone", "phone_codes", ["phone"])

    op.drop_index("ix_telegram_link_codes_user_id", table_name="telegram_link_codes")
    op.drop_table("telegram_link_codes")


def downgrade() -> None:
    op.create_table(
        "telegram_link_codes",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_telegram_link_codes_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_link_codes"),
        sa.UniqueConstraint("code_hash", name="uq_telegram_link_codes_code_hash"),
    )
    op.create_index("ix_telegram_link_codes_user_id", "telegram_link_codes", ["user_id"])
    op.drop_index("ix_phone_codes_phone", table_name="phone_codes")
    op.drop_table("phone_codes")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_column("users", "phone")
