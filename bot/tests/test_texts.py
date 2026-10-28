from __future__ import annotations

from datetime import datetime, timedelta, timezone

from calmap_bot import keyboards, texts
from calmap_bot.backend import SubscriptionState
from calmap_bot.tariffs import Tariff

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
TARIFFS = {
    "base": Tariff("base", "BASE", 299, 30, ("рацион",)),
    "pro": Tariff("pro", "PRO", 499, 30, ("всё из BASE", "AI-консультант")),
}


def state(name: str, tier: str | None, until: datetime | None) -> SubscriptionState:
    return SubscriptionState(
        state=name, has_access=name in ("trial", "active"), tier=tier,
        paid_until=until if name != "trial" else None,
        access_until=until if name in ("trial", "active") else None,
    )


def callbacks(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


def test_russian_plurals_and_dates():
    assert [texts.days_word(n) for n in (1, 2, 5, 11, 21, 22, 25)] == [
        "1 день", "2 дня", "5 дней", "11 дней", "21 день", "22 дня", "25 дней",
    ]
    assert texts.date(NOW) == "15 октября 2026"
    assert texts.when(NOW + timedelta(hours=2), NOW) == "сегодня, 15 октября"
    assert texts.when(NOW + timedelta(days=1), NOW) == "завтра, 16 октября"
    assert texts.when(NOW + timedelta(days=3), NOW) == "через 3 дня, 18 октября"


def test_progress_bar_shows_what_is_left():
    assert texts.progress_bar(30, 30) == "▰" * 10
    assert texts.progress_bar(15, 30) == "▰" * 5 + "▱" * 5
    assert texts.progress_bar(1, 30).startswith("▰")  # never looks empty while active
    assert texts.progress_bar(0, 30) == "▱" * 10


def test_price_per_day_is_honest_rounding():
    assert texts.per_day(TARIFFS["base"]) == "≈10 ₽ в день"
    assert texts.per_day(TARIFFS["pro"]) == "≈17 ₽ в день"


def test_active_card_offers_one_tap_renewal_and_upgrade():
    current = state("active", "base", NOW + timedelta(days=12))
    card = texts.home(current, TARIFFS, NOW)
    assert "BASE" in card and "ещё 12 дней" in card and "27 октября 2026" in card
    data = callbacks(keyboards.home(current, TARIFFS, True))
    assert data[0] == "offer:base" and "offer:pro" in data and "reminders:off" in data


def test_ending_soon_and_ended_cards_reassure_about_data():
    soon = texts.home(state("active", "pro", NOW + timedelta(days=2)), TARIFFS, NOW)
    assert "ничего не сгорит" in soon
    ended = state("expired", "pro", NOW - timedelta(days=1))
    card = texts.home(ended, TARIFFS, NOW)
    assert "закончилась" in card and "сохранены" in card
    assert callbacks(keyboards.home(ended, TARIFFS, False))[0] == "offer:pro"


def test_trial_card_lists_both_tariffs():
    trial = state("trial", "trial", NOW + timedelta(days=2))
    assert "Пробный период" in texts.home(trial, TARIFFS, NOW)
    data = callbacks(keyboards.home(trial, TARIFFS, True))
    assert data[:2] == ["offer:base", "offer:pro"]


def test_confirmation_shows_the_new_end_date_and_terms():
    current = state("active", "base", NOW + timedelta(days=10))
    text = texts.confirm(TARIFFS["pro"], current, NOW + timedelta(days=36), "https://x/legal/terms")
    assert "499 ₽" in text and "20 ноября 2026" in text
    assert "пересчитаны" in text and "Без автопродления" in text
    assert 'href="https://x/legal/terms"' in text


def test_settings_values_are_escaped():
    assert "<script>" not in texts.help_text("<script>")
    assert "&lt;script&gt;" in texts.help_text("<script>")


def test_reminder_buttons():
    paid = keyboards.reminder("1d", "base", False, TARIFFS)
    assert callbacks(paid) == ["offer:base", "offer:pro", "reminders:off"]
    trial = keyboards.reminder("3d", "trial", True, TARIFFS)
    assert callbacks(trial) == ["offer:base", "offer:pro", "reminders:off"]
    ended = keyboards.reminder("ended", "pro", False, TARIFFS)
    assert callbacks(ended) == ["offer:pro"]
    assert "закончилась" in texts.reminder("ended", "pro", False, NOW)


def test_login_texts():
    from calmap_bot import texts

    assert texts.masked_phone("79991234567") == "+7 999 ***-**-67"
    assert "5 минут" in texts.login_code("000111", "79991234567", 300)
    assert "2 минуты" in texts.login_too_often(150)
    assert "1 секунду" in texts.login_too_often(1)
