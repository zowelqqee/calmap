"""Trigram GIN index for the product name search.

Revision ID: b8d3f6a1c472
Revises: a4c7e9b2d815
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b8d3f6a1c472"
down_revision: Union[str, None] = "a4c7e9b2d815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_trgm is a trusted extension (PostgreSQL 13+): the database owner may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.drop_index("ix_products_name_trgm", table_name="products")
    op.execute(
        "CREATE INDEX ix_products_name_trgm ON products USING gin (lower(name) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_products_name_trgm", table_name="products")
    op.create_index("ix_products_name_trgm", "products", ["name"], unique=False)
