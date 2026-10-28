"""Subscription status from the Telegram bot; remove in-app payment providers.

* `subscriptions`: one row per user with payment_status / paid_until / trial_ends_at.
  Existing accounts get a fresh 3-day trial from the migration time so testers are
  not locked out on deploy; a still-running paid period is kept as `paid`.
* new `telegram_links`, `telegram_link_codes`, `subscription_events`.
* `payments` and `billing_events` (YooKassa/CloudPayments) are dropped.

Revision ID: d7e2f1a9b350
Revises: c4d91b7e2a10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7e2f1a9b350"
down_revision: Union[str, None] = "c4d91b7e2a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
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
    op.drop_table("billing_events")
    op.drop_index("ix_payments_provider_payment_id", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")

    # --- subscriptions: one row per user ---------------------------------------
    op.execute(
        """
        DELETE FROM subscriptions s
        USING subscriptions newer
        WHERE s.user_id = newer.user_id
          AND (s.updated_at, s.id::text) < (newer.updated_at, newer.id::text)
        """
    )
    op.add_column(
        "subscriptions",
        sa.Column("payment_status", sa.String(length=16), server_default="none", nullable=False),
    )
    op.add_column("subscriptions", sa.Column("paid_until", sa.DateTime(timezone=True)))
    op.add_column("subscriptions", sa.Column("trial_ends_at", sa.DateTime(timezone=True)))
    op.add_column("subscriptions", sa.Column("last_event_id", sa.String(length=128)))
    op.execute(
        """
        UPDATE subscriptions SET
            paid_until = CASE WHEN tier IN ('base', 'pro') THEN current_period_end END,
            payment_status = CASE
                WHEN tier IN ('base', 'pro') AND current_period_end > now() THEN 'paid'
                WHEN tier IN ('base', 'pro') THEN 'expired'
                ELSE 'none'
            END,
            trial_ends_at = now() + interval '3 days'
        """
    )
    op.alter_column("subscriptions", "tier", existing_type=sa.String(length=16), nullable=True)
    op.execute("UPDATE subscriptions SET tier = NULL WHERE tier NOT IN ('base', 'pro')")
    op.drop_index("ix_subscriptions_provider_subscription_id", table_name="subscriptions")
    for column in (
        "status",
        "provider",
        "provider_subscription_id",
        "price_rub",
        "current_period_end",
        "auto_renew",
        "raw_payload",
    ):
        op.drop_column("subscriptions", column)
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"], unique=True)
    op.execute(
        """
        INSERT INTO subscriptions (id, user_id, payment_status, trial_ends_at)
        SELECT gen_random_uuid(), u.id, 'none', now() + interval '3 days'
        FROM users u
        WHERE NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.user_id = u.id)
        """
    )

    # --- Telegram ---------------------------------------------------------------
    op.create_table(
        "telegram_links",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=64)),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_telegram_links_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_links"),
        sa.UniqueConstraint("telegram_user_id", name="uq_telegram_links_telegram_user_id"),
    )
    op.create_index("ix_telegram_links_user_id", "telegram_links", ["user_id"], unique=True)

    op.create_table(
        "telegram_link_codes",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        *_timestamps(),
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

    op.create_table(
        "subscription_events",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tier", sa.String(length=16)),
        sa.Column("paid_until", sa.DateTime(timezone=True)),
        sa.Column("amount", sa.Float()),
        sa.Column("currency", sa.String(length=3)),
        sa.Column("telegram_payment_charge_id", sa.String(length=255)),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_subscription_events_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subscription_events"),
        sa.UniqueConstraint("event_id", name="uq_subscription_events_event_id"),
    )
    op.create_index("ix_subscription_events_user_id", "subscription_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_subscription_events_user_id", table_name="subscription_events")
    op.drop_table("subscription_events")
    op.drop_index("ix_telegram_link_codes_user_id", table_name="telegram_link_codes")
    op.drop_table("telegram_link_codes")
    op.drop_index("ix_telegram_links_user_id", table_name="telegram_links")
    op.drop_table("telegram_links")

    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.add_column(
        "subscriptions",
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
    )
    op.add_column(
        "subscriptions",
        sa.Column("provider", sa.String(length=24), server_default="manual", nullable=False),
    )
    op.add_column(
        "subscriptions", sa.Column("provider_subscription_id", sa.String(length=128))
    )
    op.add_column("subscriptions", sa.Column("price_rub", sa.Float()))
    op.add_column("subscriptions", sa.Column("current_period_end", sa.DateTime(timezone=True)))
    op.add_column(
        "subscriptions",
        sa.Column("auto_renew", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_subscriptions_provider_subscription_id",
        "subscriptions",
        ["provider_subscription_id"],
    )
    op.execute(
        "UPDATE subscriptions SET current_period_end = paid_until, "
        "tier = COALESCE(tier, 'free')"
    )
    op.alter_column("subscriptions", "tier", existing_type=sa.String(length=16), nullable=False)
    for column in ("payment_status", "paid_until", "trial_ends_at", "last_event_id"):
        op.drop_column("subscriptions", column)

    op.create_table(
        "payments",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("amount_rub", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=128)),
        sa.Column("checkout_url", sa.Text()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_payments_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_provider_payment_id", "payments", ["provider_payment_id"])
    op.create_table(
        "billing_events",
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_billing_events"),
        sa.UniqueConstraint("provider", "event_id", name="uq_billing_events_provider"),
    )
