import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.jobs.recipe_images import recipe_image_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler = asyncio.create_task(recipe_image_scheduler())
    try:
        yield
    finally:
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)


media_root = Path(settings.recipe_image_storage_dir).parent
media_root.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="calmap API",
    version="0.1.0",
    description=(
        "Budget-aware nutrition planning for the Russian market. "
        "Energy targets and meal-plan optimisation are deterministic and computed "
        "server-side; models are used for photo recognition and recipe imagery, "
        "never for arithmetic."
    ),
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.mount("/media", StaticFiles(directory=media_root), name="media")


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "env": settings.env}
