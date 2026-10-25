"""Sign-in by a Russian mobile number confirmed with a one-time code.

149-FZ names authorisation by the subscriber number of a Russian operator as one of
the permitted methods. Codes are six digits, live five minutes, allow five attempts
and are stored only as an HMAC. Sending is limited per number, per IP (the auth rate
limiter) and per day for the whole service, so SMS spend cannot be pumped.

A code goes out by SMS or through our Telegram bot. The bot asks for the code only
after the user shares their own contact, which Telegram confirms for the sender's
account; limits for those codes count per Telegram account instead of per network.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import PhoneCode
from app.services.sms import get_sms_provider

logger = logging.getLogger(__name__)

_RU_MOBILE = re.compile(r"^79[0-9]{9}$")


class PhoneAuthError(ValueError):
    """User-facing refusal; `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def normalize_phone(raw: str) -> str | None:
    """+7 999 123-45-67, 8 (999) 123-45-67 or 9991234567 → 79991234567; None if the
    number is not a Russian mobile number."""
    # ASCII digits only: Unicode digits (٩, ９) would make distinct strings for one
    # number and multiply the per-number limits.
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits if _RU_MOBILE.match(digits) else None


def _hash(phone: str, code: str) -> str:
    # A key derived for this purpose only, not the JWT signing key itself.
    key = hmac.new(settings.secret_key.encode(), b"calmap:phone-code", hashlib.sha256).digest()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def network_key(ip: str | None) -> str | None:
    """The unit SMS limits are counted by: the IPv4 address or the IPv6 /64 network
    (one subscriber usually holds a whole /64)."""
    if not ip:
        return None
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


@dataclass(frozen=True, slots=True)
class IssuedCode:
    expires_in: int
    resend_in: int
    #: The code itself, only for the Telegram channel: the bot delivers it.
    code: str | None = None


Purpose = Literal["sign_in", "delete_account"]
Channel = Literal["sms", "telegram"]

MESSAGES: dict[str, str] = {
    "sign_in": "Calmap: код входа {code}. Никому его не сообщайте.",
    "delete_account": (
        "Calmap: код для УДАЛЕНИЯ аккаунта {code}. Если вы не удаляете аккаунт, "
        "никому его не сообщайте."
    ),
}


async def issue_code(
    session: AsyncSession,
    phone: str,
    ip: str | None,
    purpose: Purpose = "sign_in",
    channel: Channel = "sms",
    network: str | None = None,
) -> IssuedCode:
    """`network` replaces the IP-derived limit key (the bot passes "tg:<user id>")."""
    # Serialise requests for one number until the transaction ends, so parallel
    # requests cannot all pass the limits below before any of them is recorded.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"sms:{phone}"}
    )
    now = datetime.now(timezone.utc)
    network = network or network_key(ip)
    last_sent = await session.scalar(
        select(func.max(PhoneCode.created_at)).where(PhoneCode.phone == phone)
    )
    if last_sent is not None:
        wait = settings.phone_code_resend_seconds - int((now - last_sent).total_seconds())
        if wait > 0:
            raise PhoneAuthError(429, "code was sent recently", retry_after=wait)
    hour_ago = now - timedelta(hours=1)
    sent_last_hour = await session.scalar(
        select(func.count())
        .select_from(PhoneCode)
        .where(PhoneCode.phone == phone, PhoneCode.created_at > hour_ago)
    )
    # Per (number, network): a stranger requesting codes for someone's number uses
    # up their own allowance, not the owner's. The per-number total stays bounded.
    from_network = await session.scalar(
        select(func.count())
        .select_from(PhoneCode)
        .where(
            PhoneCode.phone == phone,
            PhoneCode.created_at > hour_ago,
            PhoneCode.ip_address.is_not_distinct_from(network),
        )
    )
    if (
        (from_network or 0) >= settings.phone_codes_per_hour
        or (sent_last_hour or 0) >= 2 * settings.phone_codes_per_hour
    ):
        raise PhoneAuthError(429, "too many codes for this number", retry_after=3600)
    if network is not None:
        # Rotating numbers from one network must not drain the daily budget.
        sent_from_network = await session.scalar(
            select(func.count())
            .select_from(PhoneCode)
            .where(
                PhoneCode.ip_address == network,
                PhoneCode.created_at > now - timedelta(days=1),
            )
        )
        if (sent_from_network or 0) >= settings.sms_per_network_daily:
            raise PhoneAuthError(429, "too many codes from this network", retry_after=3600)
    if channel == "sms":
        # Telegram codes cost nothing and do not use up the SMS budget.
        sent_today = await session.scalar(
            select(func.count())
            .select_from(PhoneCode)
            .where(PhoneCode.created_at > now - timedelta(days=1), PhoneCode.channel == "sms")
        )
        if (sent_today or 0) >= settings.sms_daily_limit:
            logger.error(
                "daily SMS limit %s reached; SMS sign-in is paused", settings.sms_daily_limit
            )
            raise PhoneAuthError(503, "sms limit reached")
        if (sent_today or 0) == int(settings.sms_daily_limit * 0.8):
            logger.warning("80%% of the daily SMS limit used (%s)", sent_today)

    # Codes hold a phone number: nothing older than a day is kept.
    await session.execute(delete(PhoneCode).where(PhoneCode.created_at < now - timedelta(days=1)))
    # Earlier unused codes for this number and purpose stop working.
    await session.execute(
        update(PhoneCode)
        .where(
            PhoneCode.phone == phone,
            PhoneCode.purpose == purpose,
            PhoneCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        PhoneCode(
            phone=phone,
            purpose=purpose,
            channel=channel,
            code_hash=_hash(phone, code),
            expires_at=now + timedelta(seconds=settings.phone_code_ttl_seconds),
            ip_address=network,
        )
    )
    await session.flush()
    if channel == "telegram":
        return IssuedCode(
            expires_in=settings.phone_code_ttl_seconds,
            resend_in=settings.phone_code_resend_seconds,
            code=code,
        )
    await get_sms_provider().send(phone, MESSAGES[purpose].format(code=code), ip)
    return IssuedCode(
        expires_in=settings.phone_code_ttl_seconds,
        resend_in=settings.phone_code_resend_seconds,
    )


async def check_code(
    session: AsyncSession, phone: str, code: str, purpose: Purpose = "sign_in"
) -> PhoneCode:
    """Validate without consuming; the caller consumes after the action succeeds."""
    now = datetime.now(timezone.utc)
    row = await session.scalar(
        select(PhoneCode)
        .where(
            PhoneCode.phone == phone,
            PhoneCode.purpose == purpose,
            PhoneCode.consumed_at.is_(None),
        )
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
