"""Entry point: Telegram long polling, the YooKassa webhook server and periodic
jobs (payment reconciliation every minute, reminders every hour) in one process."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiohttp import web

from calmap_bot import texts
from calmap_bot.backend import CalmapBackend
from calmap_bot.billing import Billing
from calmap_bot.config import get_settings
from calmap_bot.db import Database
from calmap_bot.handlers import build_router
from calmap_bot.reminders import send_reminders
from calmap_bot.tariffs import tariffs
from calmap_bot.web import build_app
from calmap_bot.yookassa import YooKassa

logger = logging.getLogger("calmap_bot")

RECONCILE_EVERY = 60
REMIND_EVERY = 3600


async def _every(seconds: int, job, name: str) -> None:
    while True:
        try:
            await job()
        except Exception:  # noqa: BLE001 — keep the loop alive
            logger.exception("%s failed", name)
        await asyncio.sleep(seconds)


async def run() -> None:
    settings = get_settings()
    missing = settings.configured
    if missing:
        logger.error("bot is not configured, missing: %s", ", ".join(missing))
        sys.exit(1)

    db = Database(settings.database_url)
    await db.create_schema()
    # Telegram through the tunnel abroad when TELEGRAM_PROXY_URL is set.
    session = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    bot = Bot(
        settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    backend = CalmapBackend(settings.calmap_api_url, settings.telegram_bot_api_secret)
    yookassa = YooKassa(settings.yookassa_shop_id, settings.yookassa_secret_key)

    async def notify(telegram_user_id: int, text: str, markup=None) -> None:
        await bot.send_message(
            telegram_user_id, text, reply_markup=markup, disable_web_page_preview=True
        )

    billing = Billing(
        db,
        yookassa,
        backend,
        notify,
        tariffs=tariffs(settings),
        return_url=settings.yookassa_return_url,
        send_receipts=settings.yookassa_receipts,
        vat_code=settings.yookassa_vat_code,
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings, db, backend, billing))
    await bot.set_my_commands(
        [
            BotCommand(command="status", description="📅 Моя подписка"),
            BotCommand(command="pay", description="💳 Продлить или оформить"),
            BotCommand(command="help", description="❓ Помощь и вопросы"),
        ]
    )

    try:
        await bot.set_my_description(texts.BOT_DESCRIPTION)
        await bot.set_my_short_description(texts.BOT_SHORT_DESCRIPTION)
    except Exception:  # noqa: BLE001 — cosmetics must not stop the bot
        logger.warning("could not update the bot description")

    runner = web.AppRunner(build_app(billing))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.web_port).start()
    jobs = [
        asyncio.create_task(_every(RECONCILE_EVERY, billing.reconcile, "reconcile")),
        asyncio.create_task(
            _every(REMIND_EVERY, lambda: send_reminders(db, backend, notify, billing.tariffs), "reminders")
        ),
    ]
    logger.info("bot started")
    try:
        await dispatcher.start_polling(bot)
    finally:
        for job in jobs:
            job.cancel()
        await runner.cleanup()
        await backend.close()
        await yookassa.close()
        await bot.session.close()
        await db.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL at INFO; those carry Telegram user IDs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run())


if __name__ == "__main__":
    main()
