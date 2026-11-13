"""App Store subscriptions (In-App Purchase): Apple-signed data in, access out.

The app sends the transaction StoreKit returned (a JWS signed by Apple) right
after a purchase or a restore; Apple sends renewals, refunds and expiries to
/v1/appstore/notifications. Both are verified against Apple's root certificate
before anything is stored: a forged or foreign transaction is refused.

Each Apple subscription (originalTransactionId) belongs to one app account. The
app passes the account id as appAccountToken when it buys; a transaction that
already belongs to another account is refused rather than moved, so one Apple
subscription cannot open several accounts.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.models.JWSTransactionDecodedPayload import (
    JWSTransactionDecodedPayload,
)
from appstoreserverlibrary.models.ResponseBodyV2DecodedPayload import (
    ResponseBodyV2DecodedPayload,
)
from appstoreserverlibrary.signed_data_verifier import (
    SignedDataVerifier,
    VerificationException,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AppleSubscription, User

logger = logging.getLogger(__name__)

#: Higher tier wins when the bot and the App Store both give access.
TIER_RANK = {"base": 1, "pro": 2}


class AppStoreUnavailable(RuntimeError):
    """Apple's root certificate is not installed: purchases cannot be verified."""


class InvalidAppStoreData(ValueError):
    """Not a valid Apple-signed transaction or notification for this app."""


class SubscriptionOwnedElsewhere(ValueError):
    """The Apple subscription already belongs to another app account."""


@dataclass(frozen=True, slots=True)
class AppleEntitlement:
    tier: str
    expires_at: datetime


def product_tiers() -> dict[str, str]:
    return {settings.apple_product_base: "base", settings.apple_product_pro: "pro"}


def _root_certificates() -> list[bytes]:
    directory = Path(settings.apple_root_certs_dir)
    certificates = sorted(directory.glob("*.cer")) if directory.is_dir() else []
    return [path.read_bytes() for path in certificates]


@lru_cache
def _verifiers() -> tuple[SignedDataVerifier, ...]:
    """Production first, then Sandbox (TestFlight and App Review buy in Sandbox)."""
    roots = _root_certificates()
    if not roots:
        raise AppStoreUnavailable("no Apple root certificates in APPLE_ROOT_CERTS_DIR")
    verifiers = [
        SignedDataVerifier(roots, False, Environment.SANDBOX, settings.apple_bundle_id)
    ]
    if settings.apple_app_id:
        verifiers.insert(
            0,
            SignedDataVerifier(
                roots, False, Environment.PRODUCTION, settings.apple_bundle_id,
                settings.apple_app_id,
            ),
        )
    # Offline checks: the chain is verified as of the transaction's signing date.
    return tuple(verifiers)


def decode_transaction(signed_transaction: str) -> JWSTransactionDecodedPayload:
    for verifier in _verifiers():
        try:
            return verifier.verify_and_decode_signed_transaction(signed_transaction)
        except VerificationException:
            continue
    raise InvalidAppStoreData("transaction is not signed by Apple for this app")


def decode_notification(signed_payload: str) -> ResponseBodyV2DecodedPayload:
    for verifier in _verifiers():
        try:
            return verifier.verify_and_decode_notification(signed_payload)
        except VerificationException:
            continue
    raise InvalidAppStoreData("notification is not signed by Apple for this app")


def decode_notification_transaction(
    notification: ResponseBodyV2DecodedPayload,
) -> JWSTransactionDecodedPayload | None:
    data = notification.data
    if data is None or not data.signedTransactionInfo:
        return None
    return decode_transaction(data.signedTransactionInfo)


def _moment(milliseconds: int | None) -> datetime | None:
    if milliseconds is None:
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)


def _account_token(transaction: JWSTransactionDecodedPayload) -> uuid.UUID | None:
    try:
        return uuid.UUID(transaction.appAccountToken) if transaction.appAccountToken else None
    except ValueError:
        return None


async def apply_transaction(
    session: AsyncSession,
    transaction: JWSTransactionDecodedPayload,
    user: User | None = None,
) -> AppleSubscription | None:
    """Store what the transaction says about its subscription.

    `user` is the signed-in account for a purchase or restore sent by the app;
    None for Apple's notifications, which find the account by the subscription or
    by appAccountToken. Returns None when the transaction is not ours to store
    (another product type, unknown account).
    """
    tier = product_tiers().get(transaction.productId or "")
    if tier is None or not transaction.originalTransactionId or not transaction.expiresDate:
        raise InvalidAppStoreData("not a Calmap subscription transaction")
    if user is not None:
        token = _account_token(transaction)
        if token is not None and token != user.id:
            raise SubscriptionOwnedElsewhere("bought for another account")

    row = await session.scalar(
        select(AppleSubscription).where(
            AppleSubscription.original_transaction_id == transaction.originalTransactionId
        )
    )
    if row is not None and user is not None and row.user_id != user.id:
        raise SubscriptionOwnedElsewhere("restored on another account")
    if row is None:
        owner_id = user.id if user is not None else _account_token(transaction)
        if owner_id is None or await session.get(User, owner_id) is None:
            logger.warning(
                "App Store transaction %s has no Calmap account", transaction.transactionId
            )
            return None
        row = AppleSubscription(
            user_id=owner_id,
            original_transaction_id=transaction.originalTransactionId,
            environment=str(transaction.rawEnvironment or ""),
        )
        session.add(row)

    purchased_at = _moment(transaction.purchaseDate) or datetime.now(timezone.utc)
    revoked_at = _moment(transaction.revocationDate)
    is_current = row.transaction_id is None or row.transaction_id == transaction.transactionId
    is_newer = row.purchased_at is None or purchased_at >= row.purchased_at
    # Notifications can arrive out of order; an older renewal must not shorten
    # the period, and a transaction replaced by an upgrade no longer counts.
    if (is_newer and not transaction.isUpgraded) or is_current:
        row.transaction_id = str(transaction.transactionId)
        row.product_id = str(transaction.productId)
        row.tier = tier
        row.purchased_at = purchased_at
        row.expires_at = _moment(transaction.expiresDate)  # type: ignore[assignment]
        row.revoked_at = revoked_at
    await session.flush()
    return row


async def apple_entitlement(
    session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
) -> AppleEntitlement | None:
    """The best App Store subscription active now, if any."""
    now = now or datetime.now(timezone.utc)
    rows = (
        await session.scalars(
            select(AppleSubscription).where(
                AppleSubscription.user_id == user_id,
                AppleSubscription.revoked_at.is_(None),
                AppleSubscription.expires_at > now,
            )
        )
    ).all()
    if not rows:
        return None
    best = max(rows, key=lambda row: (TIER_RANK.get(row.tier, 0), row.expires_at))
    return AppleEntitlement(tier=best.tier, expires_at=best.expires_at)
