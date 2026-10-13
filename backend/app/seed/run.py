"""Idempotent catalogue seeder: `python -m app.seed.run`."""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Product, ProductPrice, Recipe, RecipeItem
from app.db.session import SessionLocal
from app.seed.data import PRODUCTS, RECIPES

MIN_PORTION_RATIO = 0.6
# 1.5x the base portion is roughly where a dish stops looking like a normal serving.
# A per-meal-type ceiling (snacks smaller than mains) is the natural refinement once
# the catalogue is big enough to afford the lost solver freedom.
MAX_PORTION_RATIO = 1.5
PORTION_FLOOR_G = 60.0
PORTION_CEILING_G = 600.0


async def seed_products(session: AsyncSession) -> dict[str, Product]:
    existing = {
        p.slug: p for p in (await session.scalars(select(Product))).all()
    }
    out: dict[str, Product] = {}
    for row in PRODUCTS:
        product = existing.get(row["slug"])
        if product is None:
            product = Product(slug=row["slug"])
            session.add(product)
        product.name = row["name"]
        product.category = row["category"]
        product.kcal_per_100g = row["kcal"]
        product.protein_per_100g = row["protein"]
        product.fat_per_100g = row["fat"]
        product.carbs_per_100g = row["carbs"]
        product.fiber_per_100g = row.get("fiber", 0.0)
        product.tags = row.get("tags", [])
        product.allergens = row.get("allergens", [])
        product.source = "curated"
        out[row["slug"]] = product
    await session.flush()
    return out


async def seed_prices(session: AsyncSession, products: dict[str, Product]) -> None:
    region = settings.default_region_code
    today = date.today()
    known = {
        (p.product_id, p.region_code)
        for p in (await session.scalars(select(ProductPrice))).all()
    }
    for row in PRODUCTS:
        product = products[row["slug"]]
        if (product.id, region) in known:
            continue
        session.add(
            ProductPrice(
                product_id=product.id,
                region_code=region,
                price_per_kg=row["price_per_kg"],
                currency=settings.default_currency,
                valid_from=today,
                source="curated_moscow_avg",
            )
        )
    await session.flush()


async def seed_recipes(session: AsyncSession, products: dict[str, Product]) -> None:
    existing = {r.slug: r for r in (await session.scalars(select(Recipe))).all()}

    for row in RECIPES:
        # Aggregate the composition first: every column is NOT NULL, so the row has to
        # be complete before it reaches the database.
        base_grams = 0.0
        totals = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
        tags: set[str] = set()
        allergens: set[str] = set()

        for slug, grams in row["items"].items():
            product = products[slug]
            base_grams += grams
            factor = grams / 100.0
            totals["kcal"] += product.kcal_per_100g * factor
            totals["protein"] += product.protein_per_100g * factor
            totals["fat"] += product.fat_per_100g * factor
            totals["carbs"] += product.carbs_per_100g * factor
            tags.update(product.tags)
            allergens.update(product.allergens)

        recipe = existing.get(row["slug"])
        if recipe is None:
            recipe = Recipe(slug=row["slug"])
            session.add(recipe)

        # Rebuild the composition from scratch so re-seeding is a true upsert.
        for item in list(recipe.items):
            await session.delete(item)
        recipe.items.clear()

        # Cooking losses are ignored on purpose: portions are specified as raw weights,
        # which is how the target audience actually weighs food.
        per_100 = 100.0 / base_grams
        recipe.name = row["name"]
        recipe.description = row.get("description") or "Сбалансированное блюдо из обычных продуктов."
        recipe.meal_types = row["meal_types"]
        recipe.prep_minutes = row.get("prep_minutes", 15)
        recipe.difficulty = "easy" if recipe.prep_minutes <= 15 else "medium"
        recipe.image_url = row.get("image_url")
        recipe.instructions = row.get("instructions") or [
            "Подготовьте и взвесьте все ингредиенты.",
            "Приготовьте ингредиенты до готовности удобным способом.",
            "Соедините компоненты, подавайте блюдо свежим.",
        ]
        recipe.kcal_per_100g = round(totals["kcal"] * per_100, 2)
        recipe.protein_per_100g = round(totals["protein"] * per_100, 2)
        recipe.fat_per_100g = round(totals["fat"] * per_100, 2)
        recipe.carbs_per_100g = round(totals["carbs"] * per_100, 2)
        recipe.base_grams = round(base_grams)
        recipe.min_grams = max(PORTION_FLOOR_G, round(base_grams * MIN_PORTION_RATIO))
        recipe.max_grams = min(PORTION_CEILING_G, round(base_grams * MAX_PORTION_RATIO))
        recipe.tags = sorted(tags)
        recipe.allergens = sorted(allergens)

        await session.flush()  # assigns recipe.id for brand-new rows
        for slug, grams in row["items"].items():
            session.add(
                RecipeItem(recipe_id=recipe.id, product_id=products[slug].id, grams=grams)
            )

    await session.flush()


async def main() -> None:
    async with SessionLocal() as session:
        products = await seed_products(session)
        await seed_prices(session, products)
        await seed_recipes(session, products)
        await session.commit()
    print(f"seeded {len(PRODUCTS)} products and {len(RECIPES)} recipes")


if __name__ == "__main__":
    asyncio.run(main())
