"""Sign-in by a Russian mobile number confirmed with an SMS code.

149-FZ names authorisation by the subscriber number of a Russian operator as one of
the permitted methods. Codes are six digits, live five minutes, allow five attempts
and are stored only as an HMAC. Sending is limited per number, per IP (the auth rate
limiter) and per day for the whole service, so SMS spend cannot be pumped.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import PhoneCode
from app.services.sms import get_sms_provider

_RU_MOBILE = re.compile(r"^79\d{9}$")


class PhoneAuthError(ValueError):
    """User-facing refusal; `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def normalize_phone(raw: str) -> str | None:
    """+7 999 123-45-67, 8 (999) 123-45-67 or 9991234567 → 79991234567; None if the
    number is not a Russian mobile number."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits if _RU_MOBILE.match(digits) else None


def _hash(phone: str, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class IssuedCode:
    expires_in: int
    resend_in: int


async def issue_code(session: AsyncSession, phone: str, ip: str | None) -> IssuedCode:
    now = datetime.now(timezone.utc)
    last_sent = await session.scalar(
        select(func.max(PhoneCode.created_at)).where(PhoneCode.phone == phone)
    )
    if last_sent is not None:
        wait = settings.phone_code_resend_seconds - int((now - last_sent).total_seconds())
        if wait > 0:
            raise PhoneAuthError(429, "code was sent recently", retry_after=wait)
    sent_last_hour = await session.scalar(
        select(func.count())
        .select_from(PhoneCode)
        .where(PhoneCode.phone == phone, PhoneCode.created_at > now - timedelta(hours=1))
    )
    if (sent_last_hour or 0) >= settings.phone_codes_per_hour:
        raise PhoneAuthError(429, "too many codes for this number", retry_after=3600)
    sent_today = await session.scalar(
        select(func.count())
        .select_from(PhoneCode)
        .where(PhoneCode.created_at > now - timedelta(days=1))
    )
    if (sent_today or 0) >= settings.sms_daily_limit:
        raise PhoneAuthError(503, "sms limit reached")

    # Codes hold a phone number: nothing older than a day is kept.
    await session.execute(delete(PhoneCode).where(PhoneCode.created_at < now - timedelta(days=1)))
    # Earlier unused codes for this number stop working.
    await session.execute(
        update(PhoneCode)
        .where(PhoneCode.phone == phone, PhoneCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        PhoneCode(
            phone=phone,
            code_hash=_hash(phone, code),
            expires_at=now + timedelta(seconds=settings.phone_code_ttl_seconds),
            ip_address=ip,
        )
    )
    await session.flush()
    await get_sms_provider().send(phone, f"Calmap: код входа {code}. Никому его не сообщайте.", ip)
    return IssuedCode(
        expires_in=settings.phone_code_ttl_seconds,
        resend_in=settings.phone_code_resend_seconds,
    )


async def check_code(session: AsyncSession, phone: str, code: str) -> PhoneCode:
    """Validate without consuming; the caller consumes after the sign-in succeeds."""
    now = datetime.now(timezone.utc)
    row = await session.scalar(
        select(PhoneCode)
        .where(PhoneCode.phone == phone, PhoneCode.consumed_at.is_(None))
        .order_by(PhoneCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if row is None or row.expires_at <= now or row.attempts >= settings.phone_code_max_attempts:
        raise PhoneAuthError(401, "code expired")
    if not hmac.compare_digest(row.code_hash, _hash(phone, code)):
        row.attempts += 1
        await session.flush()
        raise PhoneAuthError(401, "invalid code")
    return row
