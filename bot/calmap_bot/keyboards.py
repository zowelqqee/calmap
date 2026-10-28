"""Buttons. Callback data is short and self-describing:

home · tariffs · help · offer:<tier> · pay:<tier> · check · reminders:on|off ·
login:other
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from calmap_bot import texts
from calmap_bot.backend import SubscriptionState
from calmap_bot.tariffs import Tariff


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def share_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.SHARE_PHONE_BUTTON, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu() -> ReplyKeyboardMarkup:
    """Always under the input field once the account is linked."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.MENU_STATUS), KeyboardButton(text=texts.MENU_RENEW)],
            [KeyboardButton(text=texts.MENU_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def home(
    state: SubscriptionState, tariffs: dict[str, Tariff], reminders_enabled: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    tier = (state.tier or "").lower()
    if state.state in ("active", "expired") and tier in tariffs:
        # One tap to renew what the user already has.
        rows.append([_button(texts.renew_button(tariffs[tier]), f"offer:{tier}")])
        if tier != "pro" and "pro" in tariffs:
            rows.append([_button(texts.UPGRADE_BUTTON, "offer:pro")])
        rows.append([_button(texts.ALL_TARIFFS_BUTTON, "tariffs")])
    else:
        rows += [[_button(texts.choose_button(t), f"offer:{code}")] for code, t in tariffs.items()]
    rows.append(
        [
            _button(texts.reminders_button(reminders_enabled),
                    "reminders:off" if reminders_enabled else "reminders:on"),
            _button(texts.HELP_BUTTON, "help"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tariffs(items: dict[str, Tariff]) -> InlineKeyboardMarkup:
    rows = [[_button(texts.choose_button(t), f"offer:{code}")] for code, t in items.items()]
    rows.append([_button(texts.BACK_BUTTON, "home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm(tariff: Tariff) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(texts.pay_button(tariff), f"pay:{tariff.code}")],
            [_button(texts.BACK_BUTTON, "tariffs")],
        ]
    )


def invoice(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.GO_TO_PAYMENT, url=url)],
            [_button(texts.CHECK_PAYMENT, "check")],
        ]
    )


def login_other_phone() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button(texts.LOGIN_OTHER_PHONE_BUTTON, "login:other")]]
    )


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button(texts.BACK_BUTTON, "home")]])


def after_payment() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button(texts.MENU_STATUS, "home")]])


def reminder(
    kind: str, tier: str | None, is_trial: bool, tariffs: dict[str, Tariff]
) -> InlineKeyboardMarkup:
    """Renew in one tap from the reminder itself; a trial chooses a tariff."""
    rows: list[list[InlineKeyboardButton]] = []
    current = (tier or "").lower()
    if not is_trial and current in tariffs:
        rows.append([_button(texts.renew_button(tariffs[current]), f"offer:{current}")])
        if current != "pro" and "pro" in tariffs:
            rows.append([_button(texts.UPGRADE_BUTTON, "offer:pro")])
    else:
        rows += [[_button(texts.choose_button(t), f"offer:{code}")] for code, t in tariffs.items()]
    if kind != "ended":
        rows.append([_button(texts.STOP_REMINDERS_BUTTON, "reminders:off")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
