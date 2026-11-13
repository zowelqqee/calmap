"""Generate and persist recipe photos for today's planned menu.

The job is intentionally recipe-scoped rather than user-scoped: the same recipe is
shared by every meal plan, so one successful API call is enough for all users. A
Postgres advisory lock makes the job safe when several API workers wake up at 05:00.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models import MealPlan, MealPlanDay, MealPlanItem, Recipe
from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

MOSCOW = ZoneInfo("Europe/Moscow")
JOB_LOCK_KEY = 8_472_031


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    data: bytes
    mime_type: str = "image/png"


class RecipeImageProvider(Protocol):
    async def generate(self, recipe: Recipe) -> GeneratedImage: ...


class OpenAICompatibleRecipeImageProvider:
    """Adapter for the OpenAI Images API and compatible gateways."""

    def __init__(self) -> None:
        if not settings.recipe_image_api_key or not settings.recipe_image_base_url:
            raise RuntimeError(
                "RECIPE_IMAGE_API_KEY and RECIPE_IMAGE_BASE_URL are required"
            )
        self.model = settings.recipe_image_model

    async def generate(self, recipe: Recipe) -> GeneratedImage:
        prompt = (
            "Create a realistic editorial food photograph for a nutrition app. "
            f"Dish: {recipe.name}. "
            "Show the complete plated dish from a natural 45-degree overhead angle, "
            "appetizing but accurate to the dish name and ingredients. "
            "Neutral warm tableware, soft natural light, clean composition, "
            "no people, no hands, no text, no logos, no packaging, no watermark."
        )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": settings.recipe_image_size,
            "quality": settings.recipe_image_quality,
            "n": 1,
        }
        client_options = {"timeout": 180.0}
        if settings.openai_proxy_url:
            # Keep proxying scoped to the image provider. Other backend traffic
            # (including the mobile API) should continue using the VPS network.
            client_options.update(
                proxy=settings.openai_proxy_url,
                trust_env=False,
            )
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.post(
                f"{settings.recipe_image_base_url.rstrip('/')}/images/generations",
                headers={"Authorization": f"Bearer {settings.recipe_image_api_key}"},
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                # Keep the provider's actionable error (for example, billing or
                # project access) instead of exposing only a generic 403 traceback.
                logger.error(
                    "image provider response: HTTP %s: %s",
                    response.status_code,
                    response.text[:1000],
                )
                raise
            body = response.json()

            item = (body.get("data") or [{}])[0]
            encoded = item.get("b64_json")
            if encoded:
                return GeneratedImage(base64.b64decode(encoded), "image/png")

            image_url = item.get("url")
            if image_url:
                image_response = await client.get(image_url)
                image_response.raise_for_status()
                return GeneratedImage(
                    image_response.content,
                    image_response.headers.get("content-type", "image/png").split(";", 1)[0],
                )

        raise RuntimeError("recipe image API returned neither b64_json nor url")


def get_recipe_image_provider() -> RecipeImageProvider | None:
    if settings.recipe_image_provider == "disabled":
        return None
    if settings.recipe_image_provider == "openai_compatible":
        return OpenAICompatibleRecipeImageProvider()
    raise RuntimeError(f"unsupported recipe image provider: {settings.recipe_image_provider}")


def _planned_recipe_statement(start: date):
    return (
        select(MealPlan.user_id, MealPlanDay.day, Recipe)
        .join(MealPlanDay, MealPlanDay.plan_id == MealPlan.id)
        .join(MealPlanItem, MealPlanItem.day_id == MealPlanDay.id)
        .join(Recipe, Recipe.id == MealPlanItem.recipe_id)
        .where(MealPlan.status == "ready", MealPlanDay.day == start)
        .order_by(MealPlanDay.day, MealPlan.user_id)
    )


async def _recipes_for_plans(session: AsyncSession, start: date) -> list[Recipe]:
    """Return every missing recipe image used by today's plans.

    Images are shared by all users, so each recipe is generated once. The old job
    considered upcoming plans, which could generate images for days users had not
    reached yet and spend image credits unnecessarily.
    """
    rows = (await session.execute(_planned_recipe_statement(start))).all()
    recipes_by_id: dict[object, Recipe] = {}
    for user_id, day, recipe in rows:
        if recipe.image_url is None:
            recipes_by_id[recipe.id] = recipe
    return list(recipes_by_id.values())


def _extension(mime_type: str) -> str:
    return {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime_type, ".png")


def _persist_image(recipe: Recipe, image: GeneratedImage) -> str:
    root = Path(settings.recipe_image_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{recipe.slug}{_extension(image.mime_type)}"
    path = root / filename
    path.write_bytes(image.data)
    public_root = settings.recipe_image_public_base_url.rstrip("/")
    return f"{public_root}/media/recipes/{quote(filename)}"


async def run_recipe_image_job(
    *,
    run_date: date | None = None,
    provider: RecipeImageProvider | None = None,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    all_recipes: bool = False,
) -> int:
    """Generate missing photos for each user's nearest upcoming plan day."""
    provider = provider or get_recipe_image_provider()
    if provider is None:
        logger.info("recipe image job skipped: provider is disabled")
        return 0

    target_date = run_date or datetime.now(MOSCOW).date()
    # The advisory lock is session-level, so it must live on one dedicated connection
    # for the whole run: the ORM session hands its connection back to the pool on
    # every commit, and unlocking from another connection would leave it held forever.
    lock_engine = session_factory.kw.get("bind") or engine
    async with lock_engine.connect() as lock_connection:
        locked = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": JOB_LOCK_KEY}
        )
        if not locked:
            logger.info("recipe image job skipped: another worker owns the lock")
            return 0
        try:
            async with session_factory() as session:
                return await _generate_missing(session, provider, target_date, all_recipes)
        finally:
            await lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": JOB_LOCK_KEY}
            )


async def _generate_missing(
    session: AsyncSession,
    provider: RecipeImageProvider,
    target_date: date,
    all_recipes: bool = False,
) -> int:
    if all_recipes:
        recipes = list(
            (await session.scalars(select(Recipe).where(Recipe.image_url.is_(None)))).all()
        )
    else:
        recipes = await _recipes_for_plans(session, target_date)
    recipe_ids = [recipe.id for recipe in recipes]
    scope = "the whole catalogue" if all_recipes else f"plans for {target_date}"
    logger.info("recipe image job: %d recipes without photos in %s", len(recipe_ids), scope)
    generated = 0
    for recipe_id in recipe_ids:
        try:
            recipe = await session.get(Recipe, recipe_id)
            if recipe is None or recipe.image_url is not None:
                continue
            image = await provider.generate(recipe)
            if not image.data:
                raise RuntimeError("recipe image provider returned an empty image")
            recipe.image_url = _persist_image(recipe, image)
            await session.commit()
            generated += 1
            logger.info("generated recipe image: %s", recipe.slug)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                logger.error(
                    "image generation stopped: the provider rejected access "
                    "(HTTP %s); check API billing, project access, and key",
                    status_code,
                )
                return generated
            logger.exception("recipe image generation failed: %s", recipe_id)
        except Exception:
            await session.rollback()
            logger.exception("recipe image generation failed: %s", recipe_id)
    return generated


def _seconds_until_next_run(now: datetime) -> float:
    next_run = datetime.combine(now.date(), time(hour=5), tzinfo=MOSCOW)
    if now >= next_run:
        next_run += timedelta(days=1)
    return max(1.0, (next_run - now).total_seconds())


async def recipe_image_scheduler() -> None:
    """Keep the daily job alive inside the API process."""
    while True:
        now = datetime.now(MOSCOW)
        if now.hour >= 5:
            try:
                await run_recipe_image_job(run_date=now.date())
            except Exception:
                logger.exception("recipe image scheduler run failed")
        await asyncio.sleep(_seconds_until_next_run(datetime.now(MOSCOW)))


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # --all: photos for every recipe in the catalogue, not only today's plans.
    count = asyncio.run(run_recipe_image_job(all_recipes="--all" in sys.argv[1:]))
    print(f"generated {count} recipe images")
