"""Telegram conversation: link by phone, choose a tariff, pay by link."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy import delete

from calmap_bot import texts
from calmap_bot.backend import BackendError, CalmapBackend, NotLinked
from calmap_bot.billing import Billing, CheckoutRefused
from calmap_bot.config import Settings
from calmap_bot.db import BotUser, Database, Reminder
from calmap_bot.yookassa import YooKassaError

logger = logging.getLogger(__name__)


def normalize_phone(raw: str) -> str | None:
    """Telegram sends numbers with or without "+"; keep Russian mobiles only."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits if re.fullmatch(r"79\d{9}", digits) else None


def build_router(settings: Settings, db: Database, backend: CalmapBackend, billing: Billing) -> Router:
    router = Router()
    base = settings.public_base_url.rstrip("/")
    terms_url = f"{base}/legal/terms"
    privacy_url = f"{base}/legal/privacy"

    share_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.SHARE_PHONE_BUTTON, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    def tariffs_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=texts.tariff_button(t), callback_data=f"offer:{code}")]
                for code, t in billing.tariffs.items()
            ]
        )

    async def is_linked(telegram_user_id: int) -> bool:
        async with db.session() as session:
            return await session.get(BotUser, telegram_user_id) is not None

    async def forget(telegram_user_id: int) -> None:
        async with db.session() as session:
            await session.execute(delete(BotUser).where(BotUser.telegram_user_id == telegram_user_id))
            await session.execute(delete(Reminder).where(Reminder.telegram_user_id == telegram_user_id))

    async def show_tariffs(message: Message, telegram_user_id: int) -> None:
        try:
            state = await backend.status(telegram_user_id)
        except NotLinked:
            # The Calmap account was deleted: drop the stale phone and start over.
            await forget(telegram_user_id)
            await message.answer(texts.NEED_LINK)
            return
        except BackendError:
            await message.answer(texts.SERVICE_UNAVAILABLE)
            return
        await message.answer(texts.tariffs_intro(state), reply_markup=tariffs_keyboard())

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if await is_linked(message.from_user.id):
            await show_tariffs(message, message.from_user.id)
            return
        await message.answer(
            texts.welcome(terms_url, privacy_url),
            reply_markup=share_keyboard,
            disable_web_page_preview=True,
        )

    @router.message(F.contact)
    async def contact(message: Message) -> None:
        # Only the sender's own contact proves the number belongs to them.
        if message.contact.user_id != message.from_user.id:
            await message.answer(texts.NOT_YOUR_CONTACT, reply_markup=share_keyboard)
            return
        phone = normalize_phone(message.contact.phone_number)
        if phone is None:
            await message.answer(texts.ACCOUNT_NOT_FOUND, reply_markup=share_keyboard)
            return
        try:
            state = await backend.link(phone, message.from_user.id, message.from_user.username)
        except NotLinked:
            await message.answer(texts.ACCOUNT_NOT_FOUND, reply_markup=share_keyboard)
            return
        except BackendError:
            await message.answer(texts.SERVICE_UNAVAILABLE)
            return
        async with db.session() as session:
            await session.merge(BotUser(telegram_user_id=message.from_user.id, phone=phone))
        await message.answer(texts.status(state), reply_markup=ReplyKeyboardRemove())
        await message.answer("Выберите тариф:", reply_markup=tariffs_keyboard())

    @router.message(Command("pay"))
    async def pay(message: Message) -> None:
        if not await is_linked(message.from_user.id):
            await message.answer(texts.NEED_LINK)
            return
        await show_tariffs(message, message.from_user.id)

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        if not await is_linked(message.from_user.id):
            await message.answer(texts.NEED_LINK)
            return
        try:
            state = await backend.status(message.from_user.id)
        except NotLinked:
            await forget(message.from_user.id)
            await message.answer(texts.NEED_LINK)
            return
        except BackendError:
            await message.answer(texts.SERVICE_UNAVAILABLE)
            return
        await message.answer(texts.status(state))

    @router.message(Command("forget"))
    async def forget_me(message: Message) -> None:
        await forget(message.from_user.id)
        await message.answer(texts.FORGOTTEN, reply_markup=ReplyKeyboardRemove())

    @router.message(Command("help"))
    async def help_(message: Message) -> None:
        await message.answer(texts.help_text(settings.support_contact))

    @router.callback_query(F.data.startswith("offer:"))
    async def offer(callback: CallbackQuery) -> None:
        tier = callback.data.split(":", 1)[1]
        tariff = billing.tariffs.get(tier)
        if tariff is None:
            await callback.answer()
            return
        try:
            state = await backend.status(callback.from_user.id)
        except NotLinked:
            await callback.answer(texts.NEED_LINK, show_alert=True)
            return
        except BackendError:
            await callback.answer(texts.SERVICE_UNAVAILABLE, show_alert=True)
            return
        await callback.message.answer(
            texts.offer(tariff, state, terms_url),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=texts.pay_button(tariff), callback_data=f"pay:{tier}")]
                ]
            ),
            disable_web_page_preview=True,
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("pay:"))
    async def checkout(callback: CallbackQuery) -> None:
        tier = callback.data.split(":", 1)[1]
        tariff = billing.tariffs.get(tier)
        if tariff is None:
            await callback.answer()
            return
        try:
            url = await billing.start_checkout(callback.from_user.id, tier)
        except CheckoutRefused as exc:
            message = (
                texts.ALREADY_PAID_FAR_AHEAD if "far ahead" in str(exc) else texts.NEED_LINK
            )
            await callback.answer(message, show_alert=True)
            return
        except (YooKassaError, BackendError, NotLinked):
            logger.exception("checkout failed")
            await callback.answer(texts.SERVICE_UNAVAILABLE, show_alert=True)
            return
        await callback.message.answer(
            texts.payment_link(tariff),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=texts.GO_TO_PAYMENT, url=url)]]
            ),
        )
        await callback.answer()

    return router
