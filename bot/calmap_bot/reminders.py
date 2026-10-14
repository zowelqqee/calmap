"""Reminders before access ends: three days and one day ahead, once each."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from calmap_bot import texts
from calmap_bot.backend import BackendError, CalmapBackend
from calmap_bot.billing import Notify
from calmap_bot.db import Database, Reminder

logger = logging.getLogger(__name__)


def reminder_kind(access_until: datetime, now: datetime) -> str | None:
    left = access_until - now
    if left <= timedelta(0):
        return None
    if left <= timedelta(days=1):
        return "1d"
    if left <= timedelta(days=3):
        return "3d"
    return None


async def send_reminders(db: Database, backend: CalmapBackend, notify: Notify) -> int:
    try:
        expiring = await backend.expiring(within_hours=72)
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
            await notify(
                item.telegram_user_id,
                texts.reminder(item.tier, item.state == "trial", item.access_until),
            )
            sent += 1
        except Exception:  # noqa: BLE001 — the user may have blocked the bot
            logger.warning("reminder to %s not delivered", item.telegram_user_id)
    return sent
