"""Every message the bot sends, in one place."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from calmap_bot.backend import SubscriptionState
from calmap_bot.tariffs import Tariff

MOSCOW = ZoneInfo("Europe/Moscow")


def date(value: datetime) -> str:
    return value.astimezone(MOSCOW).strftime("%d.%m.%Y")


def welcome(terms_url: str, privacy_url: str) -> str:
    return (
        "Здравствуйте! Здесь оплачивается подписка на приложение Calmap.\n\n"
        "Чтобы найти ваш аккаунт, поделитесь номером телефона кнопкой ниже — тем же, "
        "по которому вы входите в приложение.\n\n"
        f"Пользовательское соглашение: {terms_url}\n"
        f"Политика обработки персональных данных: {privacy_url}"
    )


SHARE_PHONE_BUTTON = "Поделиться номером"
NOT_YOUR_CONTACT = "Отправьте свой номер кнопкой «Поделиться номером»."
ACCOUNT_NOT_FOUND = (
    "Аккаунт с этим номером не найден. Войдите в приложение Calmap по этому номеру "
    "и снова нажмите «Поделиться номером»."
)
NEED_LINK = "Сначала привяжите аккаунт: отправьте /start и поделитесь номером."
SERVICE_UNAVAILABLE = "Сервис временно недоступен. Попробуйте через несколько минут."
FORGOTTEN = (
    "Номер телефона удалён из бота. Записи об оплатах хранятся для бухгалтерского "
    "учёта без номера телефона. Чтобы оплатить снова, отправьте /start."
)


def status(state: SubscriptionState) -> str:
    if state.state == "active" and state.paid_until:
        return f"Подписка {(state.tier or '').upper()} действует до {date(state.paid_until)}."
    if state.state == "trial" and state.access_until:
        return f"Пробный период до {date(state.access_until)}."
    if state.state == "trial_ended":
        return "Пробный период закончился."
    if state.state == "revoked":
        return "Подписка отменена."
    return "Подписка закончилась."


def tariffs_intro(state: SubscriptionState) -> str:
    return f"{status(state)}\n\nВыберите тариф:"


def tariff_button(tariff: Tariff) -> str:
    return f"{tariff.title} — {tariff.price_rub} ₽ / {tariff.days} дней"


def offer(tariff: Tariff, state: SubscriptionState, terms_url: str) -> str:
    lines = [
        f"Тариф {tariff.title}: {tariff.price_rub} ₽ за {tariff.days} дней.",
        "",
        *[f"— {feature}" for feature in tariff.features],
        "",
        "Разовая оплата, автоматического продления и списаний нет.",
    ]
    if state.state == "active" and state.tier == tariff.code:
        lines.append("Новые дни добавятся к текущему сроку.")
    elif state.state == "active":
        lines.append(
            "Оставшиеся дни текущего тарифа пересчитаются в дни нового тарифа "
            "по стоимости и добавятся к сроку."
        )
    lines += ["", f"Оплачивая, вы принимаете Пользовательское соглашение: {terms_url}"]
    return "\n".join(lines)


def pay_button(tariff: Tariff) -> str:
    return f"Оплатить {tariff.price_rub} ₽"


def payment_link(tariff: Tariff) -> str:
    return (
        f"Счёт на {tariff.price_rub} ₽ создан. Оплатите картой или через СБП по кнопке "
        "ниже. После оплаты бот пришлёт подтверждение, а доступ в приложении откроется "
        "сам."
    )


GO_TO_PAYMENT = "Перейти к оплате"
ALREADY_PAID_FAR_AHEAD = "Подписка уже оплачена более чем на год вперёд."
TOO_MANY_CHECKOUTS = "Слишком много счетов за последний час. Попробуйте позже."


def paid(state: SubscriptionState) -> str:
    until = date(state.paid_until) if state.paid_until else "—"
    return (
        f"Оплата получена. Подписка {(state.tier or '').upper()} действует до {until}.\n"
        "Вернитесь в приложение Calmap — доступ уже открыт."
    )


PAID_ACCOUNT_MISSING = (
    "Оплата получена, но аккаунт Calmap с вашим номером не найден. Напишите в "
    "поддержку — мы продлим подписку вручную или вернём деньги."
)
REFUNDED = "Возврат оформлен, подписка отменена."


def reminder(expiring_tier: str | None, is_trial: bool, until: datetime) -> str:
    if is_trial:
        return f"Пробный период Calmap закончится {date(until)}. Оформить подписку: /pay"
    return (
        f"Подписка {(expiring_tier or '').upper()} закончится {date(until)}. "
        "Продлить: /pay"
    )


def help_text(support: str) -> str:
    contact = f"\n\nПоддержка: {support}" if support else ""
    return (
        "/start — привязать аккаунт Calmap по номеру телефона\n"
        "/pay — оплатить или продлить подписку\n"
        "/status — срок подписки\n"
        "/forget — удалить номер телефона из бота"
        f"{contact}"
    )
