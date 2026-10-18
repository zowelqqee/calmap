"""Every message the bot sends, in one place. Messages use Telegram HTML markup;
anything that comes from settings or users is escaped.

Tone: short, warm, concrete. Every screen says what happens next and offers the
next action as a button. No pressure tactics: no fake discounts, timers or
automatic renewal — the reasons to renew are the user's own data and plan."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from calmap_bot.backend import SubscriptionState
from calmap_bot.tariffs import Tariff

MOSCOW = ZoneInfo("Europe/Moscow")
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def date(value: datetime) -> str:
    """15 ноября 2026"""
    local = value.astimezone(MOSCOW)
    return f"{local.day} {MONTHS[local.month - 1]} {local.year}"


def short_date(value: datetime) -> str:
    """15 ноября"""
    local = value.astimezone(MOSCOW)
    return f"{local.day} {MONTHS[local.month - 1]}"


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(1, 'день', 'дня', 'дней') → 'день'"""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def days_word(n: int) -> str:
    return f"{n} {plural(n, 'день', 'дня', 'дней')}"


def days_left(until: datetime, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return max(0, math.ceil((until - now) / timedelta(days=1)))


def progress_bar(left: int, total: int, width: int = 10) -> str:
    """▰▰▰▰▰▰▱▱▱▱ — the share of the period still left."""
    filled = 0 if total <= 0 else max(0, min(width, round(width * left / total)))
    if left > 0 and filled == 0:
        filled = 1
    return "▰" * filled + "▱" * (width - filled)


def per_day(tariff: Tariff) -> str:
    return f"≈{round(tariff.price_rub / tariff.days)} ₽ в день"


def link(url: str, text: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(text)}</a>'


# ----------------------------------------------------- bot profile in Telegram

#: Shown on the bot's empty chat before /start (up to 512 characters).
BOT_DESCRIPTION = (
    "Подписка на Calmap — рацион под ваш бюджет, дневник питания, тренировки и "
    "AI-консультант.\n\n"
    "• Оформление и продление за минуту, картой или через СБП\n"
    "• Срок подписки всегда под рукой\n"
    "• Напоминание до окончания — без автосписаний\n\n"
    "Нажмите «Старт» и поделитесь номером, по которому входите в приложение."
)
#: Shown in the bot's profile and in shared links (up to 120 characters).
BOT_SHORT_DESCRIPTION = "Оформить и продлить подписку Calmap за минуту. Без автосписаний."

# ------------------------------------------------------------------- linking


def welcome(terms_url: str, privacy_url: str) -> str:
    return (
        "👋 <b>Привет! Это бот подписки Calmap</b> — приложения, которое составляет "
        "рацион под ваш бюджет и цели.\n\n"
        "Здесь за минуту можно оформить или продлить подписку и видеть, сколько "
        "дней осталось.\n\n"
        "Чтобы найти ваш аккаунт, нажмите <b>«📱 Поделиться номером»</b> внизу — "
        "это номер, по которому вы входите в приложение.\n\n"
        f"Продолжая, вы принимаете {link(terms_url, 'Пользовательское соглашение')} и "
        f"{link(privacy_url, 'Политику обработки персональных данных')}."
    )


SHARE_PHONE_BUTTON = "📱 Поделиться номером"
NOT_YOUR_CONTACT = (
    "Нужен ваш собственный номер. Нажмите кнопку <b>«📱 Поделиться номером»</b> внизу "
    "экрана — Telegram отправит его сам."
)
ACCOUNT_NOT_FOUND = (
    "🤔 Аккаунт с этим номером не найден.\n\n"
    "Войдите в приложение Calmap по этому номеру — аккаунт создастся сам — и снова "
    "нажмите «📱 Поделиться номером»."
)
LINKED = "✅ Аккаунт найден! Теперь всё про подписку — в этом чате, меню — внизу 👇"
WELCOME_BACK = "С возвращением! 👋 Меню — внизу."
NEED_LINK = "Сначала найдём ваш аккаунт: отправьте /start и поделитесь номером."
SERVICE_UNAVAILABLE = "Сервис временно недоступен. Попробуйте через пару минут 🙏"
FORGOTTEN = (
    "Номер телефона удалён из бота, привязка снята. Записи об оплатах хранятся для "
    "бухгалтерского учёта без номера. Вернуться — /start."
)

# ------------------------------------------------------------- main keyboard

MENU_STATUS = "📅 Моя подписка"
MENU_RENEW = "💳 Продлить"
MENU_HELP = "❓ Помощь"


# ---------------------------------------------------------------- home card


def home(state: SubscriptionState, tariffs: dict[str, Tariff], now: datetime | None = None) -> str:
    """The subscription card: what the user has, until when, and what to do next."""
    now = now or datetime.now(timezone.utc)
    tier = (state.tier or "").lower()
    period = tariffs[tier].days if tier in tariffs else 30

    if state.state == "active" and state.paid_until:
        left = days_left(state.paid_until, now)
        lines = [
            f"<b>Calmap {tier.upper()}</b> · активна ✅",
            f"до <b>{date(state.paid_until)}</b> — ещё {days_word(left)}",
            progress_bar(left, period),
        ]
        if left <= 3:
            lines += ["", "Срок подходит к концу. Продлите сейчас — новые дни добавятся к "
                          "текущему сроку, ничего не сгорит."]
        elif tier == "base" and "pro" in tariffs:
            lines += ["", "⭐ В PRO — рацион на 4 недели, 30 фото в день и AI-консультант."]
        return "\n".join(lines)

    if state.state == "trial" and state.access_until:
        left = days_left(state.access_until, now)
        return "\n".join([
            "🎁 <b>Пробный период</b>",
            f"до <b>{date(state.access_until)}</b> — ещё {days_word(left)}",
            progress_bar(left, 3),
            "",
            "Понравилось? Выберите тариф, чтобы рацион, дневник и тренировки "
            "остались с вами.",
        ])

    if state.state == "revoked":
        return (
            "Подписка отменена.\n\n"
            "Ваши данные на месте — оформите подписку, и всё снова откроется."
        )

    ended = "Пробный период закончился" if state.state == "trial_ended" else "Подписка закончилась"
    return (
        f"⏸ <b>{ended}</b>\n\n"
        "Ваш рацион, дневник питания и прогресс сохранены. Оформите подписку — и "
        "всё вернётся на место в ту же минуту."
    )


def renew_button(tariff: Tariff) -> str:
    return f"🔄 Продлить {tariff.title} · {tariff.price_rub} ₽"


def choose_button(tariff: Tariff) -> str:
    return f"{tariff.title} · {tariff.price_rub} ₽ / {tariff.days} дней"


UPGRADE_BUTTON = "⭐ Перейти на PRO"
ALL_TARIFFS_BUTTON = "Все тарифы"
BACK_BUTTON = "← Назад"
HELP_BUTTON = "❓ Помощь"


def reminders_button(enabled: bool) -> str:
    return "🔔 Напоминания: вкл" if enabled else "🔕 Напоминания: выкл"


# ------------------------------------------------------------------ tariffs


def tariffs_screen(tariffs: dict[str, Tariff]) -> str:
    blocks = ["<b>Тарифы Calmap</b>"]
    for code, tariff in tariffs.items():
        badge = " ⭐ максимум возможностей" if code == "pro" else ""
        features = "\n".join(f"• {escape(f)}" for f in tariff.features)
        blocks.append(
            f"<b>{tariff.title}</b> — {tariff.price_rub} ₽ за {days_word(tariff.days)} "
            f"({per_day(tariff)}){badge}\n{features}"
        )
    blocks.append("Разовая оплата картой или через СБП. Без автопродления.")
    return "\n\n".join(blocks)


# ------------------------------------------------------------------ confirm


def confirm(
    tariff: Tariff,
    state: SubscriptionState,
    new_until: datetime,
    terms_url: str,
    seller: str = "",
) -> str:
    lines = [
        f"<b>Calmap {tariff.title}</b> на {days_word(tariff.days)} — <b>{tariff.price_rub} ₽</b>",
        "",
        *[f"• {escape(f)}" for f in tariff.features],
        "",
        f"📅 После оплаты доступ будет до <b>{date(new_until)}</b>.",
    ]
    if state.state == "active" and state.tier == tariff.code:
        lines.append("Новые дни добавятся к текущему сроку.")
    elif state.state == "active" and state.tier:
        lines.append(
            f"Оставшиеся дни {state.tier.upper()} пересчитаны в дни {tariff.title} по "
            "стоимости и уже учтены в дате."
        )
    lines += [
        "",
        "Разовая оплата картой или через СБП. Без автопродления и скрытых списаний.",
        f"Оплачивая, вы принимаете {link(terms_url, 'Пользовательское соглашение')}.",
    ]
    if seller:
        lines.append(f"Продавец: {escape(seller)}.")
    return "\n".join(lines)


def pay_button(tariff: Tariff) -> str:
    return f"💳 Оплатить {tariff.price_rub} ₽"


def invoice(tariff: Tariff) -> str:
    return (
        f"🧾 <b>Счёт на {tariff.price_rub} ₽ готов</b>\n\n"
        "1. Нажмите «Перейти к оплате» — откроется защищённая страница ЮKassa.\n"
        "2. Оплатите картой или через СБП.\n"
        "3. Вернитесь сюда — бот пришлёт подтверждение, а доступ в приложении "
        "откроется сам.\n\n"
        "Если подтверждение не пришло за пару минут, нажмите «Я оплатил»."
    )


GO_TO_PAYMENT = "💳 Перейти к оплате"
CHECK_PAYMENT = "🔄 Я оплатил — проверить"
PAYMENT_PENDING = "Оплата ещё не поступила. Если вы уже оплатили, подождите минуту и проверьте снова."
PAYMENT_CANCELED = "Платёж отменён. Можно создать новый счёт в «💳 Продлить»."
PAYMENT_NOT_FOUND = "Неоплаченных счетов нет. Создайте новый в «💳 Продлить»."
CHECK_TOO_OFTEN = "Секунду, уже проверяем…"
PAYMENTS_SOON = (
    "Оплата подключается и скоро будет доступна прямо здесь. Пробный период в "
    "приложении уже работает."
)
ALREADY_PAID_FAR_AHEAD = "Подписка уже оплачена больше чем на год вперёд 🙂"
TOO_MANY_CHECKOUTS = "Слишком много счетов за последний час. Попробуйте позже."


def paid(state: SubscriptionState) -> str:
    until = date(state.paid_until) if state.paid_until else "—"
    return (
        f"🎉 <b>Оплата прошла!</b>\n\n"
        f"Calmap {(state.tier or '').upper()} активна до <b>{until}</b>.\n"
        "Откройте приложение — всё уже работает. Спасибо, что вы с нами 💚"
    )


PAID_ACCOUNT_MISSING = (
    "Оплата получена, но аккаунт Calmap, для которого создан счёт, не найден. "
    "Напишите в поддержку — продлим подписку вручную или вернём деньги."
)
REFUNDED = "Возврат оформлен, подписка отменена."

# ---------------------------------------------------------------- reminders

REMINDERS_OFF = "🔕 Напоминания отключены. Включить снова — кнопкой в «📅 Моя подписка» или /reminders_on."
REMINDERS_ON = "🔔 Напоминания включены: за 3 дня, за день и в день окончания."
STOP_REMINDERS_BUTTON = "🔕 Не напоминать"


def when(until: datetime, now: datetime | None = None) -> str:
    """By the Moscow calendar: «сегодня», «завтра» or «через 3 дня, 18 октября»."""
    now = now or datetime.now(timezone.utc)
    days = (until.astimezone(MOSCOW).date() - now.astimezone(MOSCOW).date()).days
    if days <= 0:
        return f"сегодня, {short_date(until)}"
    if days == 1:
        return f"завтра, {short_date(until)}"
    return f"через {days_word(days)}, {short_date(until)}"


def reminder(
    kind: str, tier: str | None, is_trial: bool, until: datetime, now: datetime | None = None
) -> str:
    """kind: 3d | 1d | ended"""
    name = (tier or "").upper()
    if kind == "ended":
        what = "Пробный период закончился" if is_trial else f"Подписка {name} закончилась"
        return (
            f"⏸ <b>{what}</b>\n\n"
            "Ваш рацион, дневник и прогресс сохранены. Оформите подписку — и всё "
            "вернётся на место в ту же минуту."
        )
    icon = "⏰" if kind == "1d" else "⏳"
    ends = when(until, now)
    if is_trial:
        return (
            f"{icon} <b>Пробный период закончится {ends}</b>\n\n"
            "Чтобы рацион, дневник питания и тренировки остались доступны, выберите "
            "тариф — это займёт минуту."
        )
    return (
        f"{icon} <b>Подписка {name} закончится {ends}</b>\n\n"
        "Продлите сейчас — новые дни добавятся к текущему сроку, ничего не сгорит."
    )


# --------------------------------------------------------------------- help


def help_text(support: str, seller: str = "") -> str:
    contact = f"\n\n💬 Поддержка: {escape(support)}" if support else ""
    if seller:
        contact += f"\nПродавец: {escape(seller)}"
    return (
        "<b>Частые вопросы</b>\n\n"
        "<b>Когда откроется доступ?</b>\nСразу после оплаты, обычно в течение минуты. "
        "Приложение обновит статус само.\n\n"
        "<b>Есть ли автопродление?</b>\nНет. Каждая оплата разовая, никаких списаний "
        "без вашего действия. Бот напомнит заранее.\n\n"
        "<b>Продлил заранее — дни сгорят?</b>\nНет, новые дни добавляются к текущему "
        "сроку.\n\n"
        "<b>Как сменить тариф?</b>\nВыберите другой тариф: оставшиеся дни пересчитаются "
        "по стоимости, дата окончания будет видна до оплаты.\n\n"
        "<b>Как вернуть деньги?</b>\nНапишите в поддержку.\n\n"
        "<b>Команды</b>\n"
        "/status — моя подписка\n"
        "/pay — тарифы и оплата\n"
        "/reminders_off, /reminders_on — напоминания\n"
        "/forget — удалить номер из бота"
        f"{contact}"
    )
