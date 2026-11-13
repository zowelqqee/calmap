"""Reminders: three days and one day before access ends, and once on the day it
ended — each once per period, with a one-tap renewal button, never to users who
turned reminders off."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from calmap_bot import keyboards, texts
from calmap_bot.backend import BackendError, CalmapBackend
from calmap_bot.billing import Notify
from calmap_bot.db import BotUser, Database, Reminder
from calmap_bot.tariffs import Tariff

logger = logging.getLogger(__name__)


#: How long after the end the "access ended" message may still be sent.
ENDED_WINDOW = timedelta(hours=48)


def reminder_kind(access_until: datetime, now: datetime) -> str | None:
    left = access_until - now
    if left <= timedelta(0):
        return "ended" if -left <= ENDED_WINDOW else None
    if left <= timedelta(days=1):
        return "1d"
    if left <= timedelta(days=3):
        return "3d"
    return None


async def send_reminders(
    db: Database, backend: CalmapBackend, notify: Notify, tariffs: dict[str, Tariff]
) -> int:
    try:
        expiring = await backend.expiring(
            within_hours=72, ended_within_hours=int(ENDED_WINDOW.total_seconds() // 3600)
        )
    except BackendError:
        logger.exception("could not load expiring subscriptions")
        return 0
    now = datetime.now(timezone.utc)
    sent = 0
    for item in expiring:
        kind = reminder_kind(item.access_until, now)
        if kind is None:
            continue
        async with db.session() as session:
            # Only users who are linked in the bot and did not turn reminders off.
            user = await session.get(BotUser, item.telegram_user_id)
            if user is None or not user.reminders_enabled:
                continue
            exists = await session.scalar(
                select(Reminder.id).where(
                    Reminder.telegram_user_id == item.telegram_user_id,
                    Reminder.access_until == item.access_until,
                    Reminder.kind == kind,
                )
            )
            if exists is not None:
                continue
            session.add(
                Reminder(
                    telegram_user_id=item.telegram_user_id,
                    access_until=item.access_until,
                    kind=kind,
                )
            )
        try:
            is_trial = item.state in ("trial", "trial_ended") or item.tier in (None, "trial")
            await notify(
                item.telegram_user_id,
                texts.reminder(kind, item.tier, is_trial, item.access_until),
                markup=keyboards.reminder(kind, item.tier, is_trial, tariffs),
            )
            sent += 1
        except Exception:  # noqa: BLE001 — the user may have blocked the bot
            logger.warning("reminder to %s not delivered", item.telegram_user_id)
    return sent
