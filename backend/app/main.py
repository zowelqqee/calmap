import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.legal import router as legal_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import engine
from app.jobs.recipe_images import recipe_image_scheduler

APP_VERSION = "1.0.0"

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")


def _warn_about_unfinished_configuration() -> None:
    if settings.env != "production":
        return
    stubs = [
        name
        for name, value in {
            "VISION_PROVIDER": settings.vision_provider,
            "ASSISTANT_PROVIDER": settings.assistant_provider,
        }.items()
        if value == "stub"
    ]
    if stubs:
        logger.warning("production is running with stub providers: %s", ", ".join(stubs))
    if settings.sms_provider == "stub":
        logger.warning("SMS_PROVIDER is stub: users cannot receive sign-in codes")
    if not settings.telegram_bot_api_secret:
        logger.warning(
            "TELEGRAM_BOT_API_SECRET is not set: subscription status cannot be updated"
        )
    if settings.assistant_provider != "stub" and not (
        settings.assistant_processor_name and settings.assistant_processor_country
    ):
        logger.warning(
            "ASSISTANT_PROCESSOR_NAME / ASSISTANT_PROCESSOR_COUNTRY are not set: "
            "the AI consent does not name who processes the data"
        )
    if not settings.legal_operator_name or not settings.legal_contact_email:
        logger.warning(
            "LEGAL_OPERATOR_NAME / LEGAL_CONTACT_EMAIL are not set: "
            "the privacy policy shows generic operator details"
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _warn_about_unfinished_configuration()
    scheduler = asyncio.create_task(recipe_image_scheduler())
    try:
        yield
    finally:
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)
        await engine.dispose()


media_root = Path(settings.recipe_image_storage_dir).parent
media_root.mkdir(parents=True, exist_ok=True)

# Interactive API docs are a development tool; production exposes them only on request.
docs_enabled = settings.env != "production" or settings.expose_docs

app = FastAPI(
    title="calmap API",
    version=APP_VERSION,
    description=(
        "Budget-aware nutrition planning for the Russian market. "
        "Energy targets and meal-plan optimisation are deterministic and computed "
        "server-side; models are used for photo recognition and recipe imagery, "
        "never for arithmetic."
    ),
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    # Credentials are only meaningful with explicit origins; browsers reject them
    # together with the debug wildcard anyway. The API itself uses bearer tokens.
    allow_credentials=settings.allowed_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера. Попробуйте позже."},
    )


app.include_router(api_router)
app.include_router(legal_router)
app.mount("/media", StaticFiles(directory=media_root), name="media")


@app.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    """Liveness and readiness in one: 200 only when the database answers."""
    try:
        async with engine.connect() as connection:
            await asyncio.wait_for(connection.execute(text("SELECT 1")), timeout=3)
    except Exception:  # noqa: BLE001 — any failure means "not ready"
        logger.exception("health check: database is unavailable")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unavailable", "version": APP_VERSION},
        )
    return JSONResponse(
        content={"status": "ok", "env": settings.env, "database": "ok", "version": APP_VERSION}
    )
