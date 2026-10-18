"""Telegram conversation.

Flow: share phone → subscription card → (renew | choose tariff) → confirmation
with the exact new end date → invoice → payment page → confirmation message.
Navigation inside one card edits that message, so the chat stays short; the
menu under the input field (Моя подписка · Продлить · Помощь) is always there.
"""

from __future__ import annotations

import logging
import re
import time

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from sqlalchemy import delete

from calmap_bot import keyboards, texts
from calmap_bot.backend import BackendError, CalmapBackend, NotLinked
from calmap_bot.billing import Billing, CheckoutRefused
from calmap_bot.config import Settings
from calmap_bot.db import BotUser, Database, Reminder
from calmap_bot.yookassa import YooKassaError

logger = logging.getLogger(__name__)

#: Minimum pause between two "I have paid" checks of one user (YooKassa calls).
CHECK_INTERVAL = 3.0


def normalize_phone(raw: str) -> str | None:
    """Telegram sends numbers with or without "+"; keep Russian mobiles only."""
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits if re.fullmatch(r"79[0-9]{9}", digits) else None


def _from_reminder(callback: CallbackQuery) -> bool:
    """Reminders start with ⏳, ⏰ or ⏸ (texts.reminder)."""
    text = callback.message.text if callback.message else None
    return bool(text) and text.startswith(("⏳", "⏰", "⏸"))


def build_router(settings: Settings, db: Database, backend: CalmapBackend, billing: Billing) -> Router:
    router = Router()
    # Payments and phone numbers belong in a private chat only: in a group, a
    # payment link or a subscription status would be visible to everyone.
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
    base = settings.public_base_url.rstrip("/")
    terms_url = f"{base}/legal/terms"
    privacy_url = f"{base}/legal/privacy"
    last_check: dict[int, float] = {}

    # ------------------------------------------------------------ helpers

    async def bot_user(telegram_user_id: int) -> BotUser | None:
        async with db.session() as session:
            return await session.get(BotUser, telegram_user_id)

    async def forget(telegram_user_id: int) -> None:
        async with db.session() as session:
            await session.execute(delete(BotUser).where(BotUser.telegram_user_id == telegram_user_id))
            await session.execute(delete(Reminder).where(Reminder.telegram_user_id == telegram_user_id))

    async def show(
        target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
    ) -> None:
        """A callback edits its card in place; a message gets a new card."""
        if isinstance(target, CallbackQuery):
            try:
                await target.message.edit_text(
                    text, reply_markup=markup, disable_web_page_preview=True
                )
            except TelegramBadRequest:
                # Same content, or a message too old to edit: send a fresh one.
                await target.message.answer(text, reply_markup=markup, disable_web_page_preview=True)
            await target.answer()
        else:
            await target.answer(text, reply_markup=markup, disable_web_page_preview=True)

    async def refuse(target: Message | CallbackQuery, text: str) -> None:
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)

    async def home(target: Message | CallbackQuery, telegram_user_id: int) -> None:
        user = await bot_user(telegram_user_id)
        if user is None:
            await refuse(target, texts.NEED_LINK)
            return
        try:
            state = await backend.status(telegram_user_id)
        except NotLinked:
            # The Calmap account was deleted or relinked: drop the stale phone.
            await forget(telegram_user_id)
            await refuse(target, texts.NEED_LINK)
            return
        except BackendError:
            await refuse(target, texts.SERVICE_UNAVAILABLE)
            return
        await show(
            target,
            texts.home(state, billing.tariffs),
            keyboards.home(state, billing.tariffs, user.reminders_enabled),
        )

    async def tariffs(target: Message | CallbackQuery, telegram_user_id: int) -> None:
        if await bot_user(telegram_user_id) is None:
            await refuse(target, texts.NEED_LINK)
            return
        await show(target, texts.tariffs_screen(billing.tariffs), keyboards.tariffs(billing.tariffs))

    async def set_reminders(target: Message | CallbackQuery, enabled: bool) -> None:
        telegram_user_id = target.from_user.id
        async with db.session() as session:
            user = await session.get(BotUser, telegram_user_id)
            if user is not None:
                user.reminders_enabled = enabled
        if user is None:
            await refuse(target, texts.NEED_LINK)
            return
        if isinstance(target, CallbackQuery) and _from_reminder(target):
            # Pressed under a reminder: keep the reminder and its renew button.
            await target.answer(
                texts.REMINDERS_ON if enabled else texts.REMINDERS_OFF, show_alert=True
            )
            return
        if isinstance(target, CallbackQuery):
            await target.answer(texts.REMINDERS_ON if enabled else texts.REMINDERS_OFF)
            await home(target, telegram_user_id)
            return
        await target.answer(texts.REMINDERS_ON if enabled else texts.REMINDERS_OFF)

    async def renew(message: Message) -> None:
        """«💳 Продлить»: straight to the offer for the current tariff, with the new
        end date; without a paid tariff yet — to the tariffs."""
        if await bot_user(message.from_user.id) is None:
            await refuse(message, texts.NEED_LINK)
            return
        try:
            state = await backend.status(message.from_user.id)
        except NotLinked:
            await forget(message.from_user.id)
            await refuse(message, texts.NEED_LINK)
            return
        except BackendError:
            await refuse(message, texts.SERVICE_UNAVAILABLE)
            return
        tier = (state.tier or "").lower()
        if state.state not in ("active", "expired") or tier not in billing.tariffs:
            await tariffs(message, message.from_user.id)
            return
        await offer_screen(message, message.from_user.id, tier)

    async def offer_screen(target: Message | CallbackQuery, telegram_user_id: int, tier: str) -> None:
        tariff = billing.tariffs[tier]
        try:
            state, new_until = await billing.preview(telegram_user_id, tier)
        except NotLinked:
            await refuse(target, texts.NEED_LINK)
            return
        except BackendError:
            await refuse(target, texts.SERVICE_UNAVAILABLE)
            return
        text = texts.confirm(tariff, state, new_until, terms_url, settings.seller_info)
        if isinstance(target, CallbackQuery) and _from_reminder(target):
            # From a reminder: keep the reminder, open the offer below it.
            await target.message.answer(
                text, reply_markup=keyboards.confirm(tariff), disable_web_page_preview=True
            )
            await target.answer()
            return
        await show(target, text, keyboards.confirm(tariff))

    # ------------------------------------------------------------ linking

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if await bot_user(message.from_user.id) is not None:
            await message.answer(texts.WELCOME_BACK, reply_markup=keyboards.main_menu())
            await home(message, message.from_user.id)
            return
        await message.answer(
            texts.welcome(terms_url, privacy_url),
            reply_markup=keyboards.share_phone(),
            disable_web_page_preview=True,
        )

    @router.message(F.contact)
    async def contact(message: Message) -> None:
        # Only the sender's own contact, shared with the button, proves the number
        # belongs to them; a forwarded message keeps the original contact.user_id.
        forwarded = (
            message.forward_origin is not None
            or message.via_bot is not None
            or bool(message.is_automatic_forward)
        )
        if forwarded or message.contact.user_id != message.from_user.id:
            await message.answer(texts.NOT_YOUR_CONTACT, reply_markup=keyboards.share_phone())
            return
        phone = normalize_phone(message.contact.phone_number)
        if phone is None:
            await message.answer(texts.ACCOUNT_NOT_FOUND, reply_markup=keyboards.share_phone())
            return
        try:
            linked = await backend.link(phone, message.from_user.id, message.from_user.username)
        except NotLinked:
            await message.answer(texts.ACCOUNT_NOT_FOUND, reply_markup=keyboards.share_phone())
            return
        except BackendError:
            await message.answer(texts.SERVICE_UNAVAILABLE)
            return
        async with db.session() as session:
            existing = await session.get(BotUser, message.from_user.id)
            await session.merge(
                BotUser(
                    telegram_user_id=message.from_user.id,
                    phone=phone,
                    calmap_user_id=linked.user_id,
                    reminders_enabled=existing.reminders_enabled if existing else True,
                )
            )
        await message.answer(texts.LINKED, reply_markup=keyboards.main_menu())
        user = await bot_user(message.from_user.id)
        await message.answer(
            texts.home(linked.subscription, billing.tariffs),
            reply_markup=keyboards.home(linked.subscription, billing.tariffs, user.reminders_enabled),
        )

    # ------------------------------------------------- commands and menu

    @router.message(Command("status"))
    @router.message(F.text == texts.MENU_STATUS)
    async def status(message: Message) -> None:
        await home(message, message.from_user.id)

    @router.message(Command("pay"))
    @router.message(F.text == texts.MENU_RENEW)
    async def pay(message: Message) -> None:
        await renew(message)

    @router.message(Command("help"))
    @router.message(F.text == texts.MENU_HELP)
    async def help_(message: Message) -> None:
        await message.answer(texts.help_text(settings.support_contact, settings.seller_info))

    @router.message(Command("reminders_off"))
    async def reminders_off(message: Message) -> None:
        await set_reminders(message, False)

    @router.message(Command("reminders_on"))
    async def reminders_on(message: Message) -> None:
        await set_reminders(message, True)

    @router.message(Command("forget"))
    async def forget_me(message: Message) -> None:
        try:
            # The backend keeps the Telegram ID for payments and reminders; drop it.
            await backend.unlink(message.from_user.id)
        except BackendError:
            await message.answer(texts.SERVICE_UNAVAILABLE)
            return
        await forget(message.from_user.id)
        await message.answer(texts.FORGOTTEN, reply_markup=ReplyKeyboardRemove())

    # ----------------------------------------------------------- callbacks

    @router.callback_query(F.data == "home")
    async def home_cb(callback: CallbackQuery) -> None:
        await home(callback, callback.from_user.id)

    @router.callback_query(F.data == "tariffs")
    async def tariffs_cb(callback: CallbackQuery) -> None:
        await tariffs(callback, callback.from_user.id)

    @router.callback_query(F.data == "help")
    async def help_cb(callback: CallbackQuery) -> None:
        await show(callback, texts.help_text(settings.support_contact, settings.seller_info), keyboards.back_home())

    @router.callback_query(F.data.in_({"reminders:on", "reminders:off"}))
    async def reminders_cb(callback: CallbackQuery) -> None:
        await set_reminders(callback, callback.data == "reminders:on")

    @router.callback_query(F.data.startswith("offer:"))
    async def offer(callback: CallbackQuery) -> None:
        tier = callback.data.split(":", 1)[1]
        tariff = billing.tariffs.get(tier)
        if tariff is None:
            await callback.answer()
            return
        if await bot_user(callback.from_user.id) is None:
            await refuse(callback, texts.NEED_LINK)
            return
        await offer_screen(callback, callback.from_user.id, tier)

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
            reason = str(exc)
            if "far ahead" in reason:
                message = texts.ALREADY_PAID_FAR_AHEAD
            elif "too many" in reason:
                message = texts.TOO_MANY_CHECKOUTS
            elif "not linked" in reason:
                message = texts.NEED_LINK
            elif "disabled" in reason:
                message = texts.PAYMENTS_SOON
            else:
                message = texts.SERVICE_UNAVAILABLE
            await refuse(callback, message)
            return
        except NotLinked:
            await refuse(callback, texts.NEED_LINK)
            return
        except (YooKassaError, BackendError):
            logger.exception("checkout failed")
            await refuse(callback, texts.SERVICE_UNAVAILABLE)
            return
        # The card becomes the invoice: the payment link stays in this private chat.
        await show(callback, texts.invoice(tariff), keyboards.invoice(url))

    @router.callback_query(F.data == "check")
    async def check(callback: CallbackQuery) -> None:
        now = time.monotonic()
        if now - last_check.get(callback.from_user.id, 0.0) < CHECK_INTERVAL:
            await callback.answer(texts.CHECK_TOO_OFTEN)
            return
        last_check[callback.from_user.id] = now
        try:
            result = await billing.check_payments(callback.from_user.id)
        except (YooKassaError, BackendError):
            logger.exception("payment check failed")
            await refuse(callback, texts.SERVICE_UNAVAILABLE)
            return
        if result == "paid":
            # The confirmation message came from billing; the invoice becomes the card.
            await home(callback, callback.from_user.id)
            return
        await refuse(
            callback,
            {
                "pending": texts.PAYMENT_PENDING,
                "canceled": texts.PAYMENT_CANCELED,
            }.get(result, texts.PAYMENT_NOT_FOUND),
        )

    # ------------------------------------------------------------ fallback

    @router.message()
    async def anything_else(message: Message) -> None:
        """Whatever the user types, they land on something useful."""
        if await bot_user(message.from_user.id) is None:
            await start(message)
            return
        await home(message, message.from_user.id)

    return router
