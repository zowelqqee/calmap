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

    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 60

    apple_client_id: str = ""
    google_client_id: str = ""
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

    # Billing is provider-agnostic in the application layer. `stub` is useful for
    # local end-to-end testing; production uses yookassa or cloudpayments.
    billing_provider: Literal["stub", "yookassa", "cloudpayments"] = "stub"
    billing_return_url: str = "http://localhost:3000/billing/complete"
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    cloudpayments_public_id: str = ""
    cloudpayments_secret: str = ""
    cloudpayments_checkout_url: str = ""

    # OAuth verification. Apple and Google use their public JWKS; VK is verified via
    # the configured user-info endpoint because VK ID access tokens are not uniform
    # JWTs across app configurations.
    oauth_jwks_cache_seconds: int = 3600
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
