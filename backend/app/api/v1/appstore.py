"""App Store subscriptions: purchases from the app, notifications from Apple."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentSubscription, CurrentUser, DbSession
from app.api.v1.subscription import subscription_out
from app.schemas.subscription import (
    AppStoreNotificationIn,
    AppStoreTransactionIn,
    SubscriptionOut,
)
from app.services.appstore import (
    AppStoreUnavailable,
    InvalidAppStoreData,
    SubscriptionOwnedElsewhere,
    apply_transaction,
    decode_notification,
    decode_notification_transaction,
    decode_transaction,
)

router = APIRouter(prefix="/appstore", tags=["appstore"])
logger = logging.getLogger(__name__)


@router.post("/transactions", response_model=SubscriptionOut)
async def submit_transaction(
    payload: AppStoreTransactionIn,
    user: CurrentUser,
    subscription: CurrentSubscription,
    session: DbSession,
) -> SubscriptionOut:
    """A purchase or a restore made in the app: verified, stored, new status back."""
    try:
        transaction = decode_transaction(payload.signed_transaction)
        await apply_transaction(session, transaction, user)
    except AppStoreUnavailable:
        logger.error("App Store purchase refused: Apple root certificate is not installed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "app store purchases are not available"
        ) from None
    except SubscriptionOwnedElsewhere:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this App Store subscription belongs to another account"
        ) from None
    except InvalidAppStoreData:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid app store transaction"
        ) from None
    return await subscription_out(session, subscription)


@router.post("/notifications", status_code=status.HTTP_200_OK)
async def app_store_notification(payload: AppStoreNotificationIn, session: DbSession) -> Response:
    """App Store Server Notifications V2: renewals, expiries, refunds, revocations.

    Anything not signed by Apple for this app is refused. Notifications without a
    subscription transaction (test notifications, other products) are accepted and
    ignored, so Apple does not keep retrying them.
    """
    try:
        notification = decode_notification(payload.signedPayload)
        transaction = decode_notification_transaction(notification)
    except AppStoreUnavailable:
        # 5xx: Apple retries later, once the certificate is installed.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "not configured") from None
    except InvalidAppStoreData:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid notification") from None
    if transaction is not None:
        try:
            await apply_transaction(session, transaction)
        except InvalidAppStoreData:
            pass  # another product: nothing of ours to update
    logger.info("App Store notification %s handled", notification.rawNotificationType)
    return Response(status_code=status.HTTP_200_OK)
