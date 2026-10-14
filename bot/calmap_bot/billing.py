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

from sqlalchemy import select, text

from calmap_bot.backend import BackendError, CalmapBackend, NotLinked, SubscriptionState
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
        """Create a YooKassa payment and return its confirmation URL."""
        tariff = self.tariffs[tier]
        async with self.db.session() as session:
            user = await session.get(BotUser, telegram_user_id)
        if user is None:
            raise CheckoutRefused("not linked")
        current = await self.backend.status(telegram_user_id)
        now = datetime.now(timezone.utc)
        if current.state == "active" and current.paid_until and current.paid_until - now > MAX_PREPAID:
            raise CheckoutRefused("prepaid too far ahead")

        record = Payment(
            telegram_user_id=telegram_user_id,
            tier=tier,
            days=tariff.days,
            amount_rub=Decimal(tariff.price_rub),
        )
        async with self.db.session() as session:
            session.add(record)
        yoo = await self.yookassa.create_payment(
            # The record id doubles as the idempotence key: a retried request
            # cannot create a second payment.
            idempotence_key=str(record.id),
            amount_rub=Decimal(tariff.price_rub),
            description=f"Подписка Calmap {tariff.title} на {tariff.days} дней",
            return_url=self.return_url,
            metadata={"payment_record": str(record.id), "telegram_user_id": telegram_user_id, "tier": tier},
            receipt_phone=user.phone if self.send_receipts else None,
            vat_code=self.vat_code,
        )
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
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": record.telegram_user_id}
            )
            try:
                current = await self.backend.status(record.telegram_user_id)
                paid_until = record.paid_until or compute_paid_until(
                    datetime.now(timezone.utc), current, self.tariffs[record.tier], self.prices
                )
                # Remember the computed end before calling the backend: a retry after
                # a lost answer then repeats the same event instead of extending twice.
                record.paid_until = paid_until
                await session.flush()
                state = await self.backend.report_paid(
                    event_id=f"yookassa:{record.yookassa_payment_id}",
                    telegram_user_id=record.telegram_user_id,
                    tier=record.tier,
                    paid_until=paid_until,
                    amount=float(record.amount_rub),
                )
            except NotLinked:
                # Paid, but the Calmap account is gone (deleted or relinked). Keep the
                # record undelivered for support and tell the user once.
                first_failure = record.delivery_error is None
                record.delivery_error = "account not found"
                logger.error("payment %s: Calmap account not found", record.id)
                if first_failure:
                    await self._safe_notify(record.telegram_user_id, "orphaned")
                return
            except BackendError as exc:
                record.delivery_error = str(exc)[:255]
                logger.exception("delivery of payment %s failed; will retry", record.id)
                return
            record.delivered_at = datetime.now(timezone.utc)
            record.delivery_error = None
        await self._safe_notify(record.telegram_user_id, "paid", state)

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
            if refund.amount < Decimal(record.amount_rub):
                logger.info("partial refund %s of payment %s ignored", refund.id, refund.payment_id)
                return
            try:
                await self.backend.report_revoked(
                    event_id=f"yookassa-refund:{refund.id}",
                    telegram_user_id=record.telegram_user_id,
                )
            except NotLinked:
                logger.info("refund %s: Calmap account no longer exists", refund.id)
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
                    select(Payment.yookassa_payment_id).where(
                        Payment.status == PaymentStatus.PENDING,
                        Payment.yookassa_payment_id.is_not(None),
                        Payment.created_at > now - PENDING_WINDOW,
                    )
                )
            ).all()
            undelivered = (
                await session.scalars(
                    select(Payment.id).where(
                        Payment.status == PaymentStatus.SUCCEEDED,
                        Payment.delivered_at.is_(None),
                    )
                )
            ).all()
        for payment_id in pending:
            try:
                await self.process_payment(payment_id)
            except Exception:  # noqa: BLE001 — one failure must not stop the loop
                logger.exception("reconciling payment %s failed", payment_id)
        for record_id in undelivered:
            await self.deliver(record_id)

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
