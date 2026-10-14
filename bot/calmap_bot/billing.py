"""Selling a subscription and reporting it to Calmap.

Lifecycle of a payment record: pending → succeeded → delivered to the backend
(paid_until fixed) → optionally refunded. Every transition is driven by the state
YooKassa reports through its API (webhook or periodic reconciliation), never by a
notification body, and is safe to repeat.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select, text

from calmap_bot.backend import (
    BackendError,
    CalmapBackend,
    LinkChanged,
    NotLinked,
    SubscriptionState,
)
from calmap_bot.db import BotUser, Database, Payment, PaymentStatus
from calmap_bot.tariffs import Tariff
from calmap_bot.yookassa import YooKassa, YooPayment

logger = logging.getLogger(__name__)

#: Sends a message to a Telegram user: notify(telegram_user_id, text).
Notify = Callable[[int, str], Awaitable[None]]

#: The backend accepts paid_until at most 400 days ahead; selling stops a year out.
MAX_PREPAID = timedelta(days=365)
BACKEND_LIMIT = timedelta(days=399)
#: How long a pending payment is polled before it is considered abandoned.
PENDING_WINDOW = timedelta(hours=24)
#: A pending checkout for the same tier is reused instead of creating another.
REUSE_PENDING = timedelta(hours=1)
#: Payments a user may create per hour; bounds YooKassa calls and reconcile work.
CHECKOUTS_PER_HOUR = 5
RECONCILE_BATCH = 200


class CheckoutRefused(ValueError):
    pass


def compute_paid_until(
    now: datetime,
    current: SubscriptionState,
    tariff: Tariff,
    prices: dict[str, int],
) -> datetime:
    """End of access after buying `tariff`.

    * Same tier still active: the new period starts at the current end.
    * Another tier still active: its remaining time is converted by price into days
      of the new tier (BASE → PRO: 20 days × 299/499 ≈ 12 days) and added.
    * Otherwise the period starts now.
    """
    start = now
    if current.state == "active" and current.paid_until and current.paid_until > now:
        remaining = current.paid_until - now
        if current.tier == tariff.code:
            start = current.paid_until
        elif current.tier in prices:
            start = now + remaining * (prices[current.tier] / tariff.price_rub)
    return min(start + timedelta(days=tariff.days), now + BACKEND_LIMIT)


class Billing:
    def __init__(
        self,
        db: Database,
        yookassa: YooKassa,
        backend: CalmapBackend,
        notify: Notify,
        *,
        tariffs: dict[str, Tariff],
        return_url: str,
        send_receipts: bool,
        vat_code: int,
    ) -> None:
        self.db = db
        self.yookassa = yookassa
        self.backend = backend
        self.notify = notify
        self.tariffs = tariffs
        self.return_url = return_url
        self.send_receipts = send_receipts
        self.vat_code = vat_code

    @property
    def prices(self) -> dict[str, int]:
        return {code: tariff.price_rub for code, tariff in self.tariffs.items()}

    # ---------------------------------------------------------------- checkout

    async def start_checkout(self, telegram_user_id: int, tier: str) -> str:
        """Create a YooKassa payment (or reuse a fresh pending one for the same
        tier) and return its confirmation URL."""
        tariff = self.tariffs[tier]
        now = datetime.now(timezone.utc)
        async with self.db.session() as session:
            user = await session.get(BotUser, telegram_user_id)
            if user is None:
                raise CheckoutRefused("not linked")
            reusable = await session.scalar(
                select(Payment)
                .where(
                    Payment.telegram_user_id == telegram_user_id,
                    Payment.calmap_user_id == user.calmap_user_id,
                    Payment.tier == tier,
                    Payment.status == PaymentStatus.PENDING,
                    Payment.confirmation_url.is_not(None),
                    Payment.created_at > now - REUSE_PENDING,
                )
                .order_by(Payment.created_at.desc())
                .limit(1)
            )
            if reusable is not None:
                return reusable.confirmation_url
            recent = await session.scalar(
                select(func.count())
                .select_from(Payment)
                .where(
                    Payment.telegram_user_id == telegram_user_id,
                    Payment.created_at > now - timedelta(hours=1),
                )
            )
            if (recent or 0) >= CHECKOUTS_PER_HOUR:
                raise CheckoutRefused("too many checkouts")
        current = await self.backend.status(telegram_user_id)
        if current.state == "active" and current.paid_until and current.paid_until - now > MAX_PREPAID:
            raise CheckoutRefused("prepaid too far ahead")

        record = Payment(
            telegram_user_id=telegram_user_id,
            calmap_user_id=user.calmap_user_id,
            tier=tier,
            days=tariff.days,
            amount_rub=Decimal(tariff.price_rub),
        )
        async with self.db.session() as session:
            session.add(record)
        try:
            yoo = await self.yookassa.create_payment(
                # The record id doubles as the idempotence key: a retried request
                # cannot create a second payment.
                idempotence_key=str(record.id),
                amount_rub=Decimal(tariff.price_rub),
                description=f"Подписка Calmap {tariff.title} на {tariff.days} дней",
                return_url=self.return_url,
                metadata={"payment_record": str(record.id)},
                receipt_phone=user.phone if self.send_receipts else None,
                vat_code=self.vat_code,
            )
        except Exception:
            async with self.db.session() as session:
                await session.execute(delete(Payment).where(Payment.id == record.id))
            raise
        async with self.db.session() as session:
            row = await session.get(Payment, record.id)
            row.yookassa_payment_id = yoo.id
            row.confirmation_url = yoo.confirmation_url
        if not yoo.confirmation_url:
            raise CheckoutRefused("no confirmation url")
        return yoo.confirmation_url

    # --------------------------------------------------------------- payments

    async def process_payment(self, yookassa_payment_id: str) -> None:
        """Bring the local record in line with YooKassa and deliver a success."""
        yoo = await self.yookassa.get_payment(yookassa_payment_id)
        async with self.db.session() as session:
            record = await session.scalar(
                select(Payment)
                .where(Payment.yookassa_payment_id == yoo.id)
                .with_for_update()
            )
            if record is None:
                logger.warning("unknown YooKassa payment %s", yoo.id)
                return
            if record.status == PaymentStatus.PENDING:
                await self._apply_status(record, yoo)
        # A canceled payment needs no message: the user saw the result on the
        # YooKassa page, and abandoned checkouts are canceled hours later.
        if record.status == PaymentStatus.SUCCEEDED and record.delivered_at is None:
            await self.deliver(record.id)

    async def _apply_status(self, record: Payment, yoo: YooPayment) -> None:
        if yoo.status == "succeeded" and yoo.paid:
            if yoo.currency != "RUB" or yoo.amount != Decimal(record.amount_rub):
                logger.error(
                    "payment %s amount %s %s does not match record %s",
                    yoo.id, yoo.amount, yoo.currency, record.amount_rub,
                )
                return
            record.status = PaymentStatus.SUCCEEDED
            record.paid_at = datetime.now(timezone.utc)
        elif yoo.status == "canceled":
            record.status = PaymentStatus.CANCELED

    async def deliver(self, record_id: uuid.UUID) -> None:
        """Report a succeeded payment to the backend exactly once.

        Deliveries for one user are serialised, so two quick purchases extend the
        period one after the other instead of both starting from the same end.
        """
        async with self.db.session() as session:
            record = await session.get(Payment, record_id, with_for_update=True)
            if record is None or record.status != PaymentStatus.SUCCEEDED or record.delivered_at:
                return
            # Namespaced key: never collides with the backend's advisory locks.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('calmap-bot:' || :id, 0))"),
                {"id": str(record.telegram_user_id)},
            )
            now = datetime.now(timezone.utc)
            try:
                current = await self.backend.status(record.telegram_user_id)
                # A period computed for an attempt the backend never accepted may
                # have gone stale; recompute it then.
                paid_until = record.paid_until
                if paid_until is None or paid_until <= now:
                    paid_until = compute_paid_until(
                        now, current, self.tariffs[record.tier], self.prices
                    )
                # Remember the computed end before calling the backend: a retry after
                # a lost answer then repeats the same event instead of extending twice.
                record.paid_until = paid_until
                await session.flush()
                state = await self.backend.report_paid(
                    event_id=f"yookassa:{record.yookassa_payment_id}",
                    telegram_user_id=record.telegram_user_id,
                    user_id=record.calmap_user_id,
                    tier=record.tier,
                    paid_until=paid_until,
                    amount=float(record.amount_rub),
                )
            except (NotLinked, LinkChanged):
                # Paid, but the account it was paid for is gone or the Telegram
                # account now points elsewhere. Never credit another account: keep
                # the record for support and tell the user once.
                first_failure = record.delivery_error is None
                record.delivery_error = "account not found or relinked"
                self._schedule_retry(record, now)
                logger.error("payment %s: paid-for Calmap account unavailable", record.id)
                if first_failure:
                    await self._safe_notify(record.telegram_user_id, "orphaned")
                return
            except BackendError as exc:
                record.delivery_error = str(exc)[:255]
                self._schedule_retry(record, now)
                logger.exception("delivery of payment %s failed; will retry", record.id)
                return
            record.delivered_at = datetime.now(timezone.utc)
            record.delivery_error = None
        await self._safe_notify(record.telegram_user_id, "paid", state)

    @staticmethod
    def _schedule_retry(record: Payment, now: datetime) -> None:
        """Exponential backoff: 2, 4, 8 … minutes, at most six hours apart."""
        record.delivery_attempts += 1
        delay = min(timedelta(minutes=2 ** record.delivery_attempts), timedelta(hours=6))
        record.next_attempt_at = now + delay

    # ---------------------------------------------------------------- refunds

    async def process_refund(self, refund_id: str) -> None:
        """A full refund cancels the subscription; partial refunds change nothing."""
        refund = await self.yookassa.get_refund(refund_id)
        if refund.status != "succeeded":
            return
        async with self.db.session() as session:
            record = await session.scalar(
                select(Payment)
                .where(Payment.yookassa_payment_id == refund.payment_id)
                .with_for_update()
            )
            if record is None or record.status == PaymentStatus.REFUNDED:
                return
            # Several partial refunds count once they add up to the whole payment.
            payment = await self.yookassa.get_payment(refund.payment_id)
            if payment.refunded < Decimal(record.amount_rub):
                logger.info("partial refund %s of payment %s ignored", refund.id, refund.payment_id)
                return
            try:
                await self.backend.report_revoked(
                    event_id=f"yookassa-refund:{refund.id}",
                    telegram_user_id=record.telegram_user_id,
                    user_id=record.calmap_user_id,
                )
            except (NotLinked, LinkChanged):
                # Only the account that paid may lose access; never another one.
                logger.info("refund %s: the paid-for account is gone or relinked", refund.id)
            except BackendError:
                logger.exception("refund %s not delivered; YooKassa will repeat it", refund.id)
                raise
            record.status = PaymentStatus.REFUNDED
            record.refunded_at = datetime.now(timezone.utc)
        await self._safe_notify(record.telegram_user_id, "refunded")

    # ---------------------------------------------------------- reconciliation

    async def reconcile(self) -> None:
        """Safety net for lost webhooks: poll recent pending payments and retry
        deliveries the backend has not accepted yet."""
        now = datetime.now(timezone.utc)
        async with self.db.session() as session:
            pending = (
                await session.scalars(
                    select(Payment.yookassa_payment_id)
                    .where(
                        Payment.status == PaymentStatus.PENDING,
                        Payment.yookassa_payment_id.is_not(None),
                        Payment.created_at > now - PENDING_WINDOW,
                    )
                    .order_by(Payment.created_at.desc())
                    .limit(RECONCILE_BATCH)
                )
            ).all()
            undelivered = (
                await session.scalars(
                    select(Payment.id)
                    .where(
                        Payment.status == PaymentStatus.SUCCEEDED,
                        Payment.delivered_at.is_(None),
                        (Payment.next_attempt_at.is_(None)) | (Payment.next_attempt_at <= now),
                    )
                    .limit(RECONCILE_BATCH)
                )
            ).all()
        for payment_id in pending:
            try:
                await self.process_payment(payment_id)
            except Exception:  # noqa: BLE001 — one failure must not stop the loop
                logger.exception("reconciling payment %s failed", payment_id)
        for record_id in undelivered:
            try:
                await self.deliver(record_id)
            except Exception:  # noqa: BLE001 — one bad record must not stop the rest
                logger.exception("delivering payment %s failed", record_id)

    # ------------------------------------------------------------- messaging

    async def _safe_notify(self, telegram_user_id: int, kind: str, state: SubscriptionState | None = None) -> None:
        from calmap_bot import texts

        message = {
            "paid": lambda: texts.paid(state),
            "orphaned": lambda: texts.PAID_ACCOUNT_MISSING,
            "refunded": lambda: texts.REFUNDED,
        }[kind]()
        try:
            await self.notify(telegram_user_id, message)
        except Exception:  # noqa: BLE001 — a blocked bot must not undo a payment
            logger.warning("could not message %s", telegram_user_id)
