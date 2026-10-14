from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentSubscription, CurrentUser, DbSession
from app.core.config import settings
from app.db.models import TIER_LIMITS, TIER_PRICES_RUB
from app.schemas.billing import BillingPlanOut, CheckoutOut, CheckoutRequest, SubscriptionOut
from app.services.billing import cancel_subscription, create_checkout, handle_webhook

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=list[BillingPlanOut])
async def plans() -> list[BillingPlanOut]:
    return [
        BillingPlanOut(tier=tier, price_rub=price, limits=TIER_LIMITS[tier])
        for tier, price in TIER_PRICES_RUB.items()
    ]


@router.post("/checkout", response_model=CheckoutOut, status_code=status.HTTP_201_CREATED)
async def checkout(payload: CheckoutRequest, user: CurrentUser, session: DbSession) -> CheckoutOut:
    if settings.env == "production" and settings.billing_provider == "stub":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "оплата временно недоступна"
        )
    try:
        payment = await create_checkout(session, user, payload.tier)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    return CheckoutOut(
        payment_id=payment.id,
        tier=payment.tier,
        amount_rub=payment.amount_rub,
        currency=payment.currency,
        status=payment.status,
        provider=payment.provider,
        checkout_url=payment.checkout_url or "",
    )


@router.get("/subscription", response_model=SubscriptionOut)
async def subscription(current: CurrentSubscription) -> SubscriptionOut:
    return SubscriptionOut(
        tier=current.tier,
        status=current.status,
        provider=current.provider,
        price_rub=current.price_rub,
        current_period_end=current.current_period_end,
        auto_renew=current.auto_renew,
        limits=current.limits,
    )


@router.post("/cancel", response_model=SubscriptionOut)
async def cancel(user: CurrentUser, session: DbSession) -> SubscriptionOut:
    current = await cancel_subscription(session, user)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "subscription not found")
    return SubscriptionOut(
        tier=current.tier,
        status=current.status,
        provider=current.provider,
        price_rub=current.price_rub,
        current_period_end=current.current_period_end,
        auto_renew=current.auto_renew,
        limits=current.limits,
    )


@router.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request, session: DbSession) -> dict:
    if provider not in {"stub", "yookassa", "cloudpayments"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unsupported billing provider")
    # Only the configured provider is accepted; the unsigned stub additionally works
    # outside production so local end-to-end tests can complete a purchase.
    enabled = provider == settings.billing_provider or provider == "stub"
    if not enabled or (provider == "stub" and settings.env == "production"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "billing provider is not enabled")
    try:
        processed = await handle_webhook(
            session, provider, await request.body(), {k.lower(): v for k, v in request.headers.items()}
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except RuntimeError as exc:
        # Provider-side outage: a 5xx makes the provider retry the delivery later.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    if provider == "cloudpayments":
        # CloudPayments treats anything but {"code": 0} as a failed delivery.
        return {"code": 0}
    return {"ok": True, "processed": processed}
