from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, func, select

from app.api.deps import CurrentUser, DbSession
from app.db.models import FavoriteRecipe, Product, Recipe
from app.schemas.tracking import ProductOut, RecipeDetailOut, RecipeIngredientOut, RecipeOut
from app.services.catalog import current_prices_per_kg

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _product_out(product: Product, prices: dict[str, float]) -> ProductOut:
    return ProductOut(
        id=product.id,
        slug=product.slug,
        name=product.name,
        category=product.category,
        barcode=product.barcode,
        kcal_per_100g=product.kcal_per_100g,
        protein_per_100g=product.protein_per_100g,
        fat_per_100g=product.fat_per_100g,
        carbs_per_100g=product.carbs_per_100g,
        allergens=product.allergens,
        price_per_kg=prices.get(product.slug),
    )


@router.get("/products", response_model=list[ProductOut])
async def search_products(
    user: CurrentUser,
    session: DbSession,
    q: str | None = Query(default=None, min_length=1, max_length=64),
    category: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
) -> list[ProductOut]:
    statement = select(Product).where(Product.is_active.is_(True))
    if q:
        # Case-insensitive substring for now. Swap for pg_trgm similarity once the
        # catalogue outgrows a few thousand rows — the index is already declared.
        statement = statement.where(func.lower(Product.name).contains(q.lower()))
    if category:
        statement = statement.where(Product.category == category)

    products = (await session.scalars(statement.order_by(Product.name).limit(limit))).all()
    prices = await current_prices_per_kg(session, user.region_code)
    return [_product_out(p, prices) for p in products]


@router.get("/products/barcode/{barcode}", response_model=ProductOut)
async def product_by_barcode(barcode: str, user: CurrentUser, session: DbSession) -> ProductOut:
    """Barcode lookup is the cheapest and most accurate logging path there is — it
    should always be tried before spending a vision call."""
    product = await session.scalar(select(Product).where(Product.barcode == barcode))
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown barcode")
    prices = await current_prices_per_kg(session, user.region_code)
    return _product_out(product, prices)


@router.get("/recipes", response_model=list[RecipeOut])
async def list_recipes(
    user: CurrentUser,
    session: DbSession,
    meal_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RecipeOut]:
    statement = select(Recipe).where(Recipe.is_active.is_(True))
    recipes = (await session.scalars(statement.order_by(Recipe.name).limit(limit))).all()
    if meal_type:
        recipes = [r for r in recipes if meal_type in r.meal_types]
    return [
        RecipeOut(
            id=r.id,
            slug=r.slug,
            name=r.name,
            meal_types=r.meal_types,
            kcal_per_100g=r.kcal_per_100g,
            protein_per_100g=r.protein_per_100g,
            fat_per_100g=r.fat_per_100g,
            carbs_per_100g=r.carbs_per_100g,
            base_grams=r.base_grams,
            prep_minutes=r.prep_minutes,
            description=r.description,
            image_url=r.image_url,
            difficulty=r.difficulty,
            tags=r.tags,
            allergens=r.allergens,
        )
        for r in recipes
    ]


@router.get("/recipes/{recipe_slug}", response_model=RecipeDetailOut)
async def recipe_detail(
    recipe_slug: str, user: CurrentUser, session: DbSession
) -> RecipeDetailOut:
    recipe = await session.scalar(select(Recipe).where(Recipe.slug == recipe_slug))
    if recipe is None or not recipe.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    prices = await current_prices_per_kg(session, user.region_code)
    ingredients = []
    total = 0.0
    for item in recipe.items:
        price = prices.get(item.product.slug)
        cost = round(price * item.grams / 1000.0, 2) if price else None
        total += cost or 0.0
        ingredients.append(
            RecipeIngredientOut(
                slug=item.product.slug,
                name=item.product.name,
                grams=item.grams,
                estimated_cost=cost,
            )
        )
    favorite = await session.scalar(
        select(FavoriteRecipe).where(
            FavoriteRecipe.user_id == user.id, FavoriteRecipe.recipe_id == recipe.id
        )
    )
    return RecipeDetailOut(
        id=recipe.id,
        slug=recipe.slug,
        name=recipe.name,
        description=recipe.description,
        image_url=recipe.image_url,
        difficulty=recipe.difficulty,
        meal_types=recipe.meal_types,
        kcal_per_100g=recipe.kcal_per_100g,
        protein_per_100g=recipe.protein_per_100g,
        fat_per_100g=recipe.fat_per_100g,
        carbs_per_100g=recipe.carbs_per_100g,
        base_grams=recipe.base_grams,
        prep_minutes=recipe.prep_minutes,
        tags=recipe.tags,
        allergens=recipe.allergens,
        instructions=recipe.instructions,
        ingredients=ingredients,
        estimated_cost=round(total, 2),
        is_favorite=favorite is not None,
    )


@router.post("/recipes/{recipe_slug}/favorite", response_model=dict)
async def add_favorite(recipe_slug: str, user: CurrentUser, session: DbSession) -> dict:
    recipe = await session.scalar(select(Recipe).where(Recipe.slug == recipe_slug))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    existing = await session.scalar(
        select(FavoriteRecipe).where(
            FavoriteRecipe.user_id == user.id, FavoriteRecipe.recipe_id == recipe.id
        )
    )
    if existing is None:
        session.add(FavoriteRecipe(user_id=user.id, recipe_id=recipe.id))
        await session.flush()
    return {"is_favorite": True}


@router.delete("/recipes/{recipe_slug}/favorite", response_model=dict)
async def remove_favorite(recipe_slug: str, user: CurrentUser, session: DbSession) -> dict:
    recipe = await session.scalar(select(Recipe).where(Recipe.slug == recipe_slug))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    await session.execute(
        delete(FavoriteRecipe).where(
            FavoriteRecipe.user_id == user.id, FavoriteRecipe.recipe_id == recipe.id
        )
    )
    return {"is_favorite": False}
