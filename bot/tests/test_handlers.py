"""The conversation driven through aiogram's dispatcher with a recording session
instead of Telegram."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Contact, Message, Update, User

from calmap_bot.config import Settings
from calmap_bot.db import BotUser
from calmap_bot.handlers import build_router


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):  # noqa: ANN001
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(
                message_id=len(self.calls),
                date=datetime.now(timezone.utc),
                chat=Chat(id=getattr(method, "chat_id", 1) or 1, type="private"),
                text=method.text,
            )
        return True

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, (SendMessage, EditMessageText))]

    def alerts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, AnswerCallbackQuery) and c.text]


@pytest.fixture
def chat(env):
    session = RecordingSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    settings = Settings(_env_file=None, public_base_url="https://api.example.ru")
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings, env.db, env.backend_client, env.billing))
    counter = iter(range(1, 10_000))

    class Chat_:
        def __init__(self) -> None:
            self.session = session

        def user(self, uid: int) -> User:
            return User(id=uid, is_bot=False, first_name="Тест")

        def message(self, uid: int, **fields) -> Message:
            return Message(
                message_id=next(counter), date=datetime.now(timezone.utc),
                chat=Chat(id=uid, type=fields.pop("chat_type", "private")),
                from_user=self.user(uid), **fields,
            )

        async def send(self, uid: int, **fields) -> None:
            update = Update(update_id=next(counter), message=self.message(uid, **fields))
            await dispatcher.feed_update(bot, update)

        async def press(self, uid: int, data: str, on_text: str = "card") -> None:
            update = Update(
                update_id=next(counter),
                callback_query=CallbackQuery(
                    id=str(next(counter)), from_user=self.user(uid), chat_instance="x",
                    data=data, message=self.message(uid, text=on_text),
                ),
            )
            await dispatcher.feed_update(bot, update)

    return Chat_()


async def test_new_user_links_by_own_contact_and_sees_the_card(env, chat):
    uid = 7_000_001
    phone = "79990000001"
    env.backend.add_account(phone, uid)
    await chat.send(uid, text="/start")
    welcome, prices = chat.session.texts()[-2:]
    assert "Поделиться номером" in welcome
    # Prices, terms and the seller are visible before linking.
    assert "299 ₽" in prices and "499 ₽" in prices and "Пользовательском соглашении" in prices

    # Someone else's contact is refused.
    await chat.send(uid, contact=Contact(phone_number=phone, first_name="x", user_id=uid + 1))
    assert "собственный номер" in chat.session.texts()[-1]

    await chat.send(uid, contact=Contact(phone_number=phone, first_name="x", user_id=uid))
    assert "Аккаунт найден" in chat.session.texts()[-2]
    assert "Пробный период" in chat.session.texts()[-1]
    async with env.db.session() as session:
        assert (await session.get(BotUser, uid)).calmap_user_id == env.backend.accounts[uid]


async def test_renew_goes_from_menu_to_invoice_in_two_taps(env, chat, linked_user):
    until = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    env.backend.subs[linked_user] = {
        "state": "active", "has_access": True, "tier": "base",
        "paid_until": until, "access_until": until,
    }
    await chat.send(linked_user, text="💳 Продлить")
    confirm = chat.session.texts()[-1]
    assert "BASE" in confirm and "299 ₽" in confirm and "После оплаты доступ будет до" in confirm

    await chat.press(linked_user, "pay:base")
    assert "Счёт на 299 ₽ готов" in chat.session.texts()[-1]
    assert env.yoo.created and env.yoo.created[-1]["amount"]["value"] == "299.00"

    await chat.press(linked_user, "check")
    assert any("не поступила" in a for a in chat.session.alerts())


async def test_reminders_toggle_and_fallback(env, chat, linked_user):
    await chat.press(linked_user, "reminders:off")
    async with env.db.session() as session:
        assert (await session.get(BotUser, linked_user)).reminders_enabled is False
    await chat.send(linked_user, text="что-нибудь непонятное")
    assert "Пробный период" in chat.session.texts()[-1]  # lands on the card


async def test_group_chats_are_ignored(chat, linked_user):
    before = len(chat.session.calls)
    await chat.send(linked_user, text="/status", chat_type="group")
    assert len(chat.session.calls) == before


async def test_preview_mode_without_yookassa_shows_everything_but_paying(env, linked_user):
    from aiohttp.test_utils import TestClient, TestServer

    from calmap_bot.billing import Billing
    from calmap_bot.web import build_app

    preview = Billing(
        env.db, None, env.backend_client, env.billing.notify,
        tariffs=env.billing.tariffs, return_url="https://t.me/x", send_receipts=True, vat_code=1,
    )
    session = RecordingSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    settings = Settings(
        _env_file=None, public_base_url="https://api.example.ru",
        seller_info="ИП Тестов Т. Т., ИНН 000000000000",
        bot_token="42:TEST", telegram_bot_api_secret="s",
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings, env.db, env.backend_client, preview))
    assert settings.configured == [] and settings.payments_enabled is False

    def update(**fields) -> Update:
        return Update(update_id=1, **fields)

    user = User(id=linked_user, is_bot=False, first_name="Т")
    card = Message(message_id=1, date=datetime.now(timezone.utc),
                   chat=Chat(id=linked_user, type="private"), from_user=user, text="card")
    await dispatcher.feed_update(bot, update(callback_query=CallbackQuery(
        id="1", from_user=user, chat_instance="x", data="offer:base", message=card)))
    offer = session.texts()[-1]
    assert "299 ₽" in offer and "ИП Тестов" not in offer
    await dispatcher.feed_update(bot, update(callback_query=CallbackQuery(
        id="2", from_user=user, chat_instance="x", data="pay:base", message=card)))
    assert any("Оплата подключается" in a for a in session.alerts())

    async with TestClient(TestServer(build_app(preview))) as client:
        response = await client.post("/yookassa/webhook", json={"event": "payment.succeeded",
                                                               "object": {"id": "x"}})
        assert response.status == 503


def test_help_names_the_seller():
    from calmap_bot import texts

    assert "Сервис Calmap. Продавец: ИП Тестов" in texts.help_text("support@calmap.ru", "ИП Тестов")
