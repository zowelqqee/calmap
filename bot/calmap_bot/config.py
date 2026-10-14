from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from the same .env as the backend (docker compose env_file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    bot_token: str = ""

    # The Calmap backend and the shared secret of its /v1/bot/* API.
    calmap_api_url: str = "http://backend:8000"
    telegram_bot_api_secret: str = ""

    # Bot payment records live in the "bot" schema of the same PostgreSQL.
    database_url: str = "postgresql+asyncpg://localhost:5432/calmap"

    # YooKassa: payment links and 54-FZ receipts.
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    #: Where YooKassa sends the user after paying (the bot's t.me link).
    yookassa_return_url: str = "https://t.me"
    #: Send a receipt (54-FZ) with each payment; requires receipts in the shop settings.
    yookassa_receipts: bool = True
    #: VAT code of the receipt item (1 — без НДС; see YooKassa vat_code values).
    yookassa_vat_code: int = 1

    price_base_rub: int = 299
    price_pro_rub: int = 499
    subscription_days: int = 30

    #: Public origin of the backend for links to /legal/terms and /legal/privacy.
    public_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLIC_BASE_URL", "RECIPE_IMAGE_PUBLIC_BASE_URL"),
    )
    support_contact: str = Field(default="", validation_alias="LEGAL_CONTACT_EMAIL")

    #: Port of the YooKassa webhook and health endpoint inside the container.
    web_port: int = 8080

    @property
    def configured(self) -> list[str]:
        """Names of required settings that are missing."""
        required = {
            "BOT_TOKEN": self.bot_token,
            "TELEGRAM_BOT_API_SECRET": self.telegram_bot_api_secret,
            "YOOKASSA_SHOP_ID": self.yookassa_shop_id,
            "YOOKASSA_SECRET_KEY": self.yookassa_secret_key,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
