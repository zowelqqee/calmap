from __future__ import annotations

from dataclasses import dataclass

from calmap_bot.config import Settings


@dataclass(frozen=True, slots=True)
class Tariff:
    code: str
    title: str
    price_rub: int
    days: int
    features: tuple[str, ...]


def tariffs(settings: Settings) -> dict[str, Tariff]:
    """What the bot sells. Features match the backend TIER_LIMITS."""
    return {
        "base": Tariff(
            code="base",
            title="BASE",
            price_rub=settings.price_base_rub,
            days=settings.subscription_days,
            features=(
                "рацион на неделю под ваш бюджет",
                "тренировки и учёт прогресса",
                "до 5 распознаваний фото в день",
            ),
        ),
        "pro": Tariff(
            code="pro",
            title="PRO",
            price_rub=settings.price_pro_rub,
            days=settings.subscription_days,
            features=(
                "всё из BASE",
                "рацион на 4 недели",
                "до 30 распознаваний фото в день",
                "AI-консультант: 200 сообщений в месяц",
            ),
        ),
    }
