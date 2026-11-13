"""App Store subscriptions: Apple-signed purchases and notifications, combined access.

Apple's real chain cannot sign test data, so a test root, intermediate and leaf with
Apple's certificate extensions stand in for it, and the verifier trusts that root.
"""

from __future__ import annotations

import base64
import datetime as dt
import time
import uuid

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from httpx import AsyncClient

from app.core.config import settings
from app.services import appstore
from tests.conftest import pay, sign_in

BUNDLE = settings.apple_bundle_id
PRO = settings.apple_product_pro
BASE = settings.apple_product_base


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _certificate(subject, key, issuer, issuer_key, *, ca: bool, extra_oid: str | None):
    now = dt.datetime.now(dt.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=not ca, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=ca, crl_sign=ca,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
    )
    if extra_oid:
        builder = builder.add_extension(
            x509.UnrecognizedExtension(x509.ObjectIdentifier(extra_oid), b"\x05\x00"),
            critical=False,
        )
    return builder.sign(issuer_key, hashes.SHA256())


class FakeApple:
    """A certificate chain shaped like Apple's, and JWS signed with it."""

    def __init__(self) -> None:
        self.root_key = ec.generate_private_key(ec.SECP256R1())
        self.root = _certificate(
            "Test Root", self.root_key, "Test Root", self.root_key, ca=True, extra_oid=None
        )
        inter_key = ec.generate_private_key(ec.SECP256R1())
        self.intermediate = _certificate(
            "Test Intermediate", inter_key, "Test Root", self.root_key, ca=True,
            extra_oid="1.2.840.113635.100.6.2.1",
        )
        self.leaf_key = ec.generate_private_key(ec.SECP256R1())
        self.leaf = _certificate(
            "Test Leaf", self.leaf_key, "Test Intermediate", inter_key, ca=False,
            extra_oid="1.2.840.113635.100.6.11.1",
        )

    def root_der(self) -> bytes:
        return self.root.public_bytes(serialization.Encoding.DER)

    def sign(self, payload: dict) -> str:
        chain = [
            base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
            for cert in (self.leaf, self.intermediate, self.root)
        ]
        return jwt.encode(payload, self.leaf_key, algorithm="ES256", headers={"x5c": chain})

    def transaction(
        self,
        *,
        account: uuid.UUID | None,
        product: str = PRO,
        original: str = "1000",
        transaction: str | None = None,
        days: float = 30,
        purchased_days_ago: float = 0,
        revoked: bool = False,
        bundle: str = BUNDLE,
    ) -> str:
        now_ms = int(time.time() * 1000)
        purchased = now_ms - int(purchased_days_ago * 86400_000)
        payload = {
            "transactionId": transaction or f"{original}-{purchased}",
            "originalTransactionId": original,
            "bundleId": bundle,
            "productId": product,
            "purchaseDate": purchased,
            "originalPurchaseDate": purchased,
            "expiresDate": purchased + int(days * 86400_000),
            "type": "Auto-Renewable Subscription",
            "inAppOwnershipType": "PURCHASED",
            "environment": "Sandbox",
            "signedDate": now_ms,
        }
        if account is not None:
            payload["appAccountToken"] = str(account)
        if revoked:
            payload["revocationDate"] = now_ms
            payload["revocationReason"] = 0
        return self.sign(payload)

    def notification(self, signed_transaction: str, kind: str = "DID_RENEW") -> str:
        return self.sign(
            {
                "notificationType": kind,
                "notificationUUID": str(uuid.uuid4()),
                "version": "2.0",
                "signedDate": int(time.time() * 1000),
                "data": {
                    "bundleId": BUNDLE,
                    "environment": "Sandbox",
                    "signedTransactionInfo": signed_transaction,
                },
            }
        )


@pytest.fixture
def apple(tmp_path, monkeypatch) -> FakeApple:
    fake = FakeApple()
    (tmp_path / "TestRoot.cer").write_bytes(fake.root_der())
    monkeypatch.setattr(settings, "apple_root_certs_dir", str(tmp_path))
    appstore._verifiers.cache_clear()
    yield fake
    appstore._verifiers.cache_clear()


async def _user_id(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get("/v1/auth/me")).json()["id"])


async def _status(client: AsyncClient) -> dict:
    return (await client.get("/v1/me/subscription")).json()


async def test_a_purchase_in_the_app_opens_its_tier(auth_client: AsyncClient, apple: FakeApple):
    account = await _user_id(auth_client)
    response = await auth_client.post(
        "/v1/appstore/transactions",
        json={"signed_transaction": apple.transaction(account=account)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "active" and body["tier"] == "pro"
    assert body["app_store_active"] is True
    assert body["limits"]["assistant_messages_per_month"] > 0

    # The same transaction again (a restore) changes nothing.
    again = await auth_client.post(
        "/v1/appstore/transactions",
        json={"signed_transaction": apple.transaction(account=account)},
    )
    assert again.status_code == 200 and again.json()["tier"] == "pro"


async def test_forged_or_foreign_transactions_are_refused(auth_client: AsyncClient, apple: FakeApple):
    account = await _user_id(auth_client)
    stranger = FakeApple()  # not the trusted root
    forged = await auth_client.post(
        "/v1/appstore/transactions",
        json={"signed_transaction": stranger.transaction(account=account)},
    )
    other_app = await auth_client.post(
        "/v1/appstore/transactions",
        json={"signed_transaction": apple.transaction(account=account, bundle="com.other.app")},
    )
    other_product = await auth_client.post(
        "/v1/appstore/transactions",
        json={"signed_transaction": apple.transaction(account=account, product="ru.calmap.app.coins")},
    )
    assert forged.status_code == 400
    assert other_app.status_code == 400
    assert other_product.status_code == 400
    assert (await _status(auth_client))["state"] == "trial"


async def test_one_apple_subscription_opens_one_account(auth_client: AsyncClient, apple: FakeApple):
    account = await _user_id(auth_client)
    bought_for_other = await auth_client.post(
        "/v1/appstore/transactions",
        json={"signed_transaction": apple.transaction(account=uuid.uuid4(), original="2000")},
    )
    assert bought_for_other.status_code == 409

    mine = apple.transaction(account=account, original="2001")
    assert (await auth_client.post(
        "/v1/appstore/transactions", json={"signed_transaction": mine}
    )).status_code == 200

    # Another account restoring the same Apple subscription is refused.
    other = await sign_in(auth_client)
    restored = await auth_client.post(
        "/v1/appstore/transactions",
        json={"signed_transaction": apple.transaction(account=None, original="2001")},
        headers={"Authorization": f"Bearer {other['access_token']}"},
    )
    assert restored.status_code == 409


async def test_notifications_renew_and_refund(
    auth_client: AsyncClient, client: AsyncClient, apple: FakeApple
):
    account = await _user_id(auth_client)
    first = apple.transaction(account=account, original="3000", days=1)
    await auth_client.post("/v1/appstore/transactions", json={"signed_transaction": first})
    short_until = (await _status(auth_client))["access_until"]

    renewal = apple.transaction(account=account, original="3000", days=31)
    renewed = await client.post(
        "/v1/appstore/notifications", json={"signedPayload": apple.notification(renewal)}
    )
    assert renewed.status_code == 200, renewed.text
    assert (await _status(auth_client))["access_until"] > short_until

    # An older renewal arriving late does not shorten the period.
    late = apple.transaction(account=account, original="3000", days=2, purchased_days_ago=1)
    await client.post("/v1/appstore/notifications", json={"signedPayload": apple.notification(late)})
    assert (await _status(auth_client))["access_until"] > short_until

    refund = apple.sign(
        {
            **jwt.decode(renewal, options={"verify_signature": False}),
            "revocationDate": int(time.time() * 1000),
            "revocationReason": 0,
        }
    )
    refunded = await client.post(
        "/v1/appstore/notifications",
        json={"signedPayload": apple.notification(refund, kind="REFUND")},
    )
    assert refunded.status_code == 200
    status = await _status(auth_client)
    assert status["app_store_active"] is False and status["state"] == "trial"


async def test_notifications_not_signed_by_apple_are_refused(client: AsyncClient, apple: FakeApple):
    stranger = FakeApple()
    forged = stranger.notification(stranger.transaction(account=uuid.uuid4()))
    response = await client.post("/v1/appstore/notifications", json={"signedPayload": forged})
    assert response.status_code == 400


async def test_the_higher_tier_of_bot_and_app_store_wins(auth_client: AsyncClient, apple: FakeApple):
    account = await _user_id(auth_client)
    await pay(auth_client, "base", days=60)
    await auth_client.post(
        "/v1/appstore/transactions",
        json={"signed_transaction": apple.transaction(account=account, original="4000", days=10)},
    )
    status = await _status(auth_client)
    assert status["tier"] == "pro" and status["state"] == "active"


async def test_without_apple_root_certificate_purchases_are_unavailable(
    auth_client: AsyncClient, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "apple_root_certs_dir", str(tmp_path / "missing"))
    appstore._verifiers.cache_clear()
    try:
        response = await auth_client.post(
            "/v1/appstore/transactions",
            json={"signed_transaction": FakeApple().transaction(account=uuid.uuid4())},
        )
        assert response.status_code == 503
    finally:
        appstore._verifiers.cache_clear()
