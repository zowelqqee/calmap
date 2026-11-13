"""Turns database rows into the plain objects the solver understands.

The solver is deliberately ignorant of SQLAlchemy: everything it needs arrives as
frozen dataclasses. That keeps the optimisation logic unit-testable without a database
and makes it obvious that prices are resolved *once*, at plan time, rather than
implicitly re-read later.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, ProductPrice, Recipe
from app.domain.enums import MealType
from app.domain.solver import Nutrients, RecipeCandidate


async def current_prices_per_kg(
    session: AsyncSession, region_code: str, on: date | None = None
) -> dict[str, float]:
    """Latest price per product slug that was already valid on `on`."""
    on = on or date.today()
    rows = await session.execute(
        select(Product.slug, ProductPrice.price_per_kg, ProductPrice.valid_from)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .where(
            ProductPrice.region_code == region_code,
            ProductPrice.valid_from <= on,
            (ProductPrice.valid_to.is_(None)) | (ProductPrice.valid_to >= on),
        )
        .order_by(Product.slug, ProductPrice.valid_from.desc())
    )
    prices: dict[str, float] = {}
    for slug, price, _valid_from in rows:
        prices.setdefault(slug, price)  # first row per slug is the newest
    return prices


async def load_recipe_candidates(
    session: AsyncSession,
    region_code: str,
    on: date | None = None,
    excluded_product_ids: frozenset[str] = frozenset(),
) -> list[RecipeCandidate]:
    """Build the solver's catalogue, costing every dish from current regional prices.

    Dishes containing any product the user excluded in the questionnaire are dropped.
    """
    prices = await current_prices_per_kg(session, region_code, on)
    recipes = (
        await session.scalars(select(Recipe).where(Recipe.is_active.is_(True)))
    ).all()

    candidates: list[RecipeCandidate] = []
    for recipe in recipes:
        if not recipe.items or recipe.base_grams <= 0:
            continue
        if excluded_product_ids and any(
            str(item.product_id) in excluded_product_ids for item in recipe.items
        ):
            continue

        cost_of_base_portion = 0.0
        priced = True
        for item in recipe.items:
            price_per_kg = prices.get(item.product.slug)
            if price_per_kg is None:
                # An unpriced ingredient would silently make the dish look free, which
                # is far worse for a budget planner than dropping the dish.
                priced = False
                break
            cost_of_base_portion += price_per_kg * item.grams / 1000.0
        if not priced:
            continue

        candidates.append(
            RecipeCandidate(
                id=recipe.slug,
                name=recipe.name,
                meal_types=frozenset(MealType(m) for m in recipe.meal_types),
                nutrients_per_100g=Nutrients(
                    kcal=recipe.kcal_per_100g,
                    protein_g=recipe.protein_per_100g,
                    fat_g=recipe.fat_per_100g,
                    carbs_g=recipe.carbs_per_100g,
                ),
                price_per_100g=cost_of_base_portion / recipe.base_grams * 100.0,
                base_grams=recipe.base_grams,
                min_grams=recipe.min_grams,
                max_grams=recipe.max_grams,
                tags=frozenset(recipe.tags),
                allergens=frozenset(recipe.allergens),
            )
        )
    return candidates
