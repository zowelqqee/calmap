from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class Product(Base, UUIDPrimaryKey, Timestamped):
    """A raw ingredient or packaged good, with nutrients per 100 g."""

    __tablename__ = "products"

    slug: Mapped[str] = mapped_column(String(96), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    barcode: Mapped[str | None] = mapped_column(String(14), index=True)

    kcal_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    protein_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    fiber_per_100g: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    #: Dietary markers used by DietType.allows(): meat, pork, poultry, fish, dairy, egg...
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    #: Allergen codes: lactose, gluten, nuts, egg, soy, fish, seafood...
    allergens: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    #: Where the nutrition figures came from — needed for auditability and for deciding
    #: which rows to trust when two sources disagree.
    source: Mapped[str] = mapped_column(String(32), default="curated", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    prices: Mapped[list[ProductPrice]] = relationship(back_populates="product")

    __table_args__ = (Index("ix_products_name_trgm", "name"),)


class ProductPrice(Base, UUIDPrimaryKey, Timestamped):
    """Versioned price, per region and (optionally) retailer.

    Versioning is not optional: without `valid_from`/`valid_to` a plan generated last
    week cannot be re-costed, and the user's "why did my budget change?" question has
    no answer.
    """

    __tablename__ = "product_prices"

    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    region_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    retailer: Mapped[str | None] = mapped_column(String(64))
    #: Roubles per kilogram — normalising to a single unit keeps the solver simple.
    price_per_kg: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), default="rosstat_avg", nullable=False)

    product: Mapped[Product] = relationship(back_populates="prices")

    __table_args__ = (
        Index("ix_product_prices_lookup", "product_id", "region_code", "valid_from"),
    )


class Recipe(Base, UUIDPrimaryKey, Timestamped):
    """A dish. Nutrients are denormalised from its items for solver speed."""

    __tablename__ = "recipes"

    slug: Mapped[str] = mapped_column(String(96), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))
    difficulty: Mapped[str] = mapped_column(String(16), default="easy", nullable=False)
    instructions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    #: Which slots this dish can fill: ["breakfast", "lunch", ...]
    meal_types: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    #: Denormalised from items; recomputed whenever items change.
    kcal_per_100g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    protein_per_100g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fat_per_100g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    carbs_per_100g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    base_grams: Mapped[float] = mapped_column(Float, default=250.0, nullable=False)
    min_grams: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    max_grams: Mapped[float] = mapped_column(Float, default=500.0, nullable=False)

    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    allergens: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    prep_minutes: Mapped[int] = mapped_column(default=15, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    items: Mapped[list[RecipeItem]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", lazy="selectin"
    )


class RecipeItem(Base, UUIDPrimaryKey):
    __tablename__ = "recipe_items"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT")
    )
    #: Grams of this product in one *base* portion of the dish.
    grams: Mapped[float] = mapped_column(Float, nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")

    __table_args__ = (UniqueConstraint("recipe_id", "product_id", name="recipe_product"),)


class FavoriteRecipe(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "favorite_recipes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), index=True
    )

    __table_args__ = (UniqueConstraint("user_id", "recipe_id", name="favorite_user_recipe"),)
