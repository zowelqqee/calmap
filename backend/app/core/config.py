from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["local", "staging", "production"] = "local"
    debug: bool = True
    secret_key: str = "dev-only-secret-key-do-not-use-in-production"
    cors_origins: str = ""

    database_url: str = "postgresql+asyncpg://localhost:5432/calmap"

    # Per-IP attempts per minute on register/login/oauth/refresh; 0 disables.
    auth_rate_limit_per_minute: int = 20

    # Public legal pages (/legal/privacy, /legal/terms). The operator details are
    # required by 152-FZ and by the app stores; they are not invented in code.
    legal_operator_name: str = ""
    legal_contact_email: str = ""
    #: Who processes AI-consultant requests on the operator's behalf and in which
    #: country (named in the AI consent; a foreign country means cross-border transfer).
    assistant_processor_name: str = ""
    assistant_processor_country: str = ""

    # /docs and /openapi.json are disabled in production unless explicitly enabled.
    expose_docs: bool = False

    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 60

    vk_client_id: str = ""

    vision_provider: Literal["stub", "gemini", "openai_compatible"] = "stub"
    gemini_api_key: str = ""
    vision_api_key: str = ""
    vision_base_url: str = ""
    vision_model: str = "gpt-4o-mini"
    llm_proxy_base_url: str = ""

    # Recipe photos are generated once per unique recipe at the daily 05:00 job.
    recipe_image_provider: Literal["disabled", "openai_compatible"] = "disabled"
    recipe_image_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("RECIPE_IMAGE_API_KEY", "OPENAI_API_KEY"),
    )
    recipe_image_base_url: str = "https://api.openai.com/v1"
    recipe_image_model: str = "gpt-image-2"
    recipe_image_size: str = "1536x1024"
    recipe_image_quality: Literal["low", "medium", "high", "auto"] = "low"
    # Shared egress proxy for OpenAI-compatible requests. Keep the old
    # RECIPE_IMAGE_PROXY_URL name as a backwards-compatible alias.
    openai_proxy_url: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_PROXY_URL", "RECIPE_IMAGE_PROXY_URL"),
    )
    recipe_image_storage_dir: str = "media/recipes"
    recipe_image_public_base_url: str = "http://127.0.0.1:8000"

    # AI nutrition assistant. The OpenAI-compatible contract also covers a local
    # gateway, YandexGPT/GigaChat proxy, or an internal model service.
    assistant_provider: Literal["stub", "openai_compatible"] = "stub"
    assistant_api_key: str = ""
    assistant_base_url: str = ""
    assistant_model: str = "gpt-4o-mini"

    # Subscriptions. Payment happens in a Telegram bot, which pushes the status to
    # /v1/bot/* authenticated with TELEGRAM_BOT_API_SECRET. The app reads it only.
    trial_days: int = 3
    telegram_bot_username: str = ""
    telegram_bot_api_secret: str = ""
    telegram_link_code_ttl_minutes: int = 30

    # VK ID sign-in: tokens are verified by the user-info endpoint with our client_id.
    vk_userinfo_url: str = "https://id.vk.com/oauth2/user_info"

    # Optional retailer aggregator. `stub` returns a clearly labelled catalogue
    # estimate (never store availability); `http` calls a configured partner API.
    # `parse_bot` is a managed adapter to the public Pyaterochka catalogue. It is
    # deliberately opt-in: it needs a vendor key and, for store-level availability,
    # the selected Pyaterochka store ID.
    retail_provider: Literal["stub", "http", "parse_bot"] = "stub"
    retail_base_url: str = ""
    retail_api_key: str = ""
    retail_parse_api_key: str = ""
    retail_parse_5ka_scraper_id: str = ""
    retail_parse_5ka_store_id: str = ""

    # Calendar days ("today", daily quotas, plan dates) follow this zone for both the
    # process (TZ) and Postgres sessions.
    app_timezone: str = "Europe/Moscow"

    default_region_code: str = "RU-MOW"
    default_currency: str = "RUB"

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.env == "production":
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if (
                len(self.secret_key) < 32
                or self.secret_key == "dev-only-secret-key-do-not-use-in-production"
                or self.secret_key.startswith("replace-with-")
            ):
                raise ValueError("SECRET_KEY must contain at least 32 characters in production")
            if self.telegram_bot_api_secret and len(self.telegram_bot_api_secret) < 32:
                raise ValueError("TELEGRAM_BOT_API_SECRET must contain at least 32 characters")
        return self

    @property
    def sync_database_url(self) -> str:
        """Alembic runs on the sync driver (psycopg3)."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    @property
    def allowed_origins(self) -> list[str]:
        configured = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return configured or (["*"] if self.debug else [])


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
