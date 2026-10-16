from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from calmap_bot.backend import SubscriptionState
from calmap_bot.billing import CHECKOUTS_PER_HOUR, CheckoutRefused, compute_paid_until
from calmap_bot.db import Payment, PaymentStatus
from calmap_bot.tariffs import Tariff

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
PRICES = {"base": 299, "pro": 499}
BASE = Tariff("base", "BASE", 299, 30, ())
PRO = Tariff("pro", "PRO", 499, 30, ())


def state(name: str, tier: str | None = None, paid_until: datetime | None = None) -> SubscriptionState:
    return SubscriptionState(state=name, has_access=name in ("trial", "active"), tier=tier,
                             paid_until=paid_until, access_until=paid_until)


def test_new_period_starts_now_without_an_active_subscription():
    for current in (state("trial", "trial"), state("expired", "base", NOW - timedelta(days=2))):
        assert compute_paid_until(NOW, current, BASE, PRICES) == NOW + timedelta(days=30)


def test_same_tier_extends_from_the_current_end():
    current = state("active", "base", NOW + timedelta(days=10))
    assert compute_paid_until(NOW, current, BASE, PRICES) == NOW + timedelta(days=40)


def test_changing_tier_converts_remaining_days_by_price():
    upgrade = compute_paid_until(NOW, state("active", "base", NOW + timedelta(days=20)), PRO, PRICES)
    assert upgrade == NOW + timedelta(days=20) * (299 / 499) + timedelta(days=30)
    downgrade = compute_paid_until(NOW, state("active", "pro", NOW + timedelta(days=20)), BASE, PRICES)
    assert downgrade == NOW + timedelta(days=20) * (499 / 299) + timedelta(days=30)


def test_period_never_exceeds_the_backend_limit():
    current = state("active", "base", NOW + timedelta(days=390))
    assert compute_paid_until(NOW, current, BASE, PRICES) == NOW + timedelta(days=399)


async def _record(env, telegram_user_id: int) -> Payment:
    async with env.db.session() as session:
        return await session.scalar(
            select(Payment)
            .where(Payment.telegram_user_id == telegram_user_id)
            .order_by(Payment.created_at.desc())
        )


async def test_checkout_creates_a_payment_with_receipt(env, linked_user):
    url = await env.billing.start_checkout(linked_user, "pro")
    assert url.startswith("https://yoomoney.example/")
    created = env.yoo.created[-1]
    assert created["amount"] == {"value": "499.00", "currency": "RUB"}
    assert created["capture"] is True
    assert created["confirmation"]["return_url"] == "https://t.me/calmap_pay_bot"
    assert created["receipt"]["customer"]["phone"] == f"7999{linked_user:07d}"
    assert created["receipt"]["items"][0]["payment_subject"] == "service"
    record = await _record(env, linked_user)
    assert created["idempotence_key"] == str(record.id)
    assert record.status == PaymentStatus.PENDING


async def test_unlinked_user_cannot_check_out(env):
    with pytest.raises(CheckoutRefused):
        await env.billing.start_checkout(123, "base")


async def test_paid_payment_is_delivered_once_and_the_user_is_told(env, linked_user):
    await env.billing.start_checkout(linked_user, "base")
    record = await _record(env, linked_user)
    env.yoo.succeed(record.yookassa_payment_id)

    await env.billing.process_payment(record.yookassa_payment_id)
    await env.billing.process_payment(record.yookassa_payment_id)  # repeated webhook

    events = list(env.backend.events.values())
    assert len(events) == 1
    assert events[0]["event_id"] == f"yookassa:{record.yookassa_payment_id}"
    assert events[0]["tier"] == "base" and events[0]["amount"] == 299
    record = await _record(env, linked_user)
    assert record.status == PaymentStatus.SUCCEEDED and record.delivered_at is not None
    assert len([m for u, m in env.sent if u == linked_user and "Оплата прошла" in m]) == 1


async def test_amount_mismatch_is_not_delivered(env, linked_user):
    await env.billing.start_checkout(linked_user, "pro")
    record = await _record(env, linked_user)
    env.yoo.succeed(record.yookassa_payment_id, amount="1.00")
    await env.billing.process_payment(record.yookassa_payment_id)
    assert not env.backend.events
    assert (await _record(env, linked_user)).status == PaymentStatus.PENDING


async def test_backend_outage_is_retried_with_the_same_period(env, linked_user):
    await env.billing.start_checkout(linked_user, "base")
    record = await _record(env, linked_user)
    env.yoo.succeed(record.yookassa_payment_id)
    env.backend.fail_events = True
    await env.billing.process_payment(record.yookassa_payment_id)
    stored = await _record(env, linked_user)
    assert stored.delivered_at is None and stored.paid_until is not None

    assert stored.delivery_attempts == 1 and stored.next_attempt_at > datetime.now(timezone.utc)
    # Backoff: the record is not retried before its time.
    env.backend.fail_events = False
    await env.billing.reconcile()
    assert (await _record(env, linked_user)).delivered_at is None
    async with env.db.session() as session:
        (await session.get(Payment, stored.id)).next_attempt_at = None
    await env.billing.reconcile()
    delivered = await _record(env, linked_user)
    assert delivered.delivered_at is not None
    sent_until = datetime.fromisoformat(next(iter(env.backend.events.values()))["paid_until"])
    assert sent_until == stored.paid_until


async def test_reconcile_picks_up_a_payment_whose_webhook_was_lost(env, linked_user):
    await env.billing.start_checkout(linked_user, "pro")
    record = await _record(env, linked_user)
    env.yoo.succeed(record.yookassa_payment_id)
    await env.billing.reconcile()
    assert (await _record(env, linked_user)).delivered_at is not None


async def test_full_refund_revokes_and_partial_does_not(env, linked_user):
    await env.billing.start_checkout(linked_user, "base")
    record = await _record(env, linked_user)
    env.yoo.succeed(record.yookassa_payment_id)
    await env.billing.process_payment(record.yookassa_payment_id)

    await env.billing.process_refund(env.yoo.refund(record.yookassa_payment_id, "100.00"))
    assert env.backend.subs[linked_user]["state"] == "active"

    # Partial refunds that add up to the whole payment cancel the subscription.
    await env.billing.process_refund(env.yoo.refund(record.yookassa_payment_id, "199.00"))
    assert env.backend.subs[linked_user]["state"] == "revoked"
    assert (await _record(env, linked_user)).status == PaymentStatus.REFUNDED


async def test_second_purchase_extends_the_first(env, linked_user):
    for _ in range(2):
        await env.billing.start_checkout(linked_user, "base")
        record = await _record(env, linked_user)
        env.yoo.succeed(record.yookassa_payment_id)
        await env.billing.process_payment(record.yookassa_payment_id)
    ends = sorted(datetime.fromisoformat(e["paid_until"]) for e in env.backend.events.values()
                  if e["telegram_user_id"] == linked_user)
    assert round((ends[1] - ends[0]).total_seconds() / 86400) == 30


async def test_purchases_stop_a_year_ahead(env, linked_user):
    far = (datetime.now(timezone.utc) + timedelta(days=370)).isoformat()
    env.backend.subs[linked_user] = {"state": "active", "has_access": True, "tier": "base",
                                     "paid_until": far, "access_until": far}
    with pytest.raises(CheckoutRefused):
        await env.billing.start_checkout(linked_user, "base")


async def test_repeated_checkout_reuses_the_pending_payment(env, linked_user):
    first = await env.billing.start_checkout(linked_user, "base")
    assert await env.billing.start_checkout(linked_user, "base") == first
    assert await env.billing.start_checkout(linked_user, "pro") != first
    assert len(env.yoo.created) >= 2


async def test_checkouts_per_hour_are_limited(env, linked_user):
    for _ in range(CHECKOUTS_PER_HOUR):
        await env.billing.start_checkout(linked_user, "base")
        # Make the previous checkout unusable so a new payment is created.
        async with env.db.session() as session:
            record = await session.scalar(
                select(Payment).where(Payment.telegram_user_id == linked_user)
                .order_by(Payment.created_at.desc())
            )
            record.status = PaymentStatus.CANCELED
    with pytest.raises(CheckoutRefused, match="too many"):
        await env.billing.start_checkout(linked_user, "base")


async def test_payment_is_never_credited_to_a_relinked_account(env, linked_user):
    await env.billing.start_checkout(linked_user, "base")
    record = await _record(env, linked_user)
    env.yoo.succeed(record.yookassa_payment_id)
    # The Telegram account was relinked to another Calmap account after checkout.
    env.backend.accounts[linked_user] = uuid.uuid4()
    await env.billing.process_payment(record.yookassa_payment_id)
    assert not [e for e in env.backend.events.values() if e["telegram_user_id"] == linked_user]
    stored = await _record(env, linked_user)
    assert stored.delivered_at is None and stored.delivery_error
    assert len([m for u, m in env.sent if u == linked_user and "не найден" in m]) == 1


async def test_preview_shows_the_end_date_before_paying(env, linked_user):
    state, until = await env.billing.preview(linked_user, "base")
    assert state.state == "trial"
    expected = datetime.now(timezone.utc) + timedelta(days=30)
    assert abs((until - expected).total_seconds()) < 5


async def test_i_have_paid_button_checks_yookassa_at_once(env, linked_user):
    assert await env.billing.check_payments(linked_user) == "none"
    await env.billing.start_checkout(linked_user, "pro")
    assert await env.billing.check_payments(linked_user) == "pending"
    record = await _record(env, linked_user)
    env.yoo.succeed(record.yookassa_payment_id)
    # No webhook arrived: the button alone delivers the payment.
    assert await env.billing.check_payments(linked_user) == "paid"
    assert (await _record(env, linked_user)).delivered_at is not None
    assert len([m for u, m in env.sent if u == linked_user and "Оплата прошла" in m]) == 1
