"""Production OAuth token verification.

The mobile client sends an identity token, never an untrusted user id. Apple and
Google are verified locally against their rotating public JWKS; VK ID is verified by
its user-info endpoint. The small in-memory JWKS cache avoids a network request on
every login while still refreshing keys on a bounded schedule.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx
import jwt

from app.core.config import settings


class OAuthVerificationError(ValueError):
    pass


@dataclass(slots=True)
class _JwksCache:
    expires_at: float = 0.0
    keys: dict[str, dict] | None = None


_CACHE: dict[str, _JwksCache] = {}

JWKS_URLS = {
    "apple": "https://appleid.apple.com/auth/keys",
    "google": "https://www.googleapis.com/oauth2/v3/certs",
}
ISSUERS = {
    "apple": "https://appleid.apple.com",
    "google": {"https://accounts.google.com", "accounts.google.com"},
}


async def _jwks(provider: str) -> dict[str, dict]:
    now = time.monotonic()
    cached = _CACHE.get(provider)
    if cached and cached.keys and cached.expires_at > now:
        return cached.keys

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(JWKS_URLS[provider])
        response.raise_for_status()
        body = response.json()
    keys = {item["kid"]: item for item in body.get("keys", []) if item.get("kid")}
    if not keys:
        raise OAuthVerificationError(f"{provider} returned no signing keys")
    _CACHE[provider] = _JwksCache(
        expires_at=now + settings.oauth_jwks_cache_seconds, keys=keys
    )
    return keys


async def _verify_jwt(provider: str, token: str) -> tuple[str, str | None]:
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        algorithm = header.get("alg")
        if not kid or algorithm not in {"RS256", "ES256"}:
            raise OAuthVerificationError("unsupported OAuth token header")

        keys = await _jwks(provider)
        key = keys.get(kid)
        if key is None:
            # A provider may have rotated keys between cache refreshes.
            _CACHE.pop(provider, None)
            key = (await _jwks(provider)).get(kid)
        if key is None:
            raise OAuthVerificationError("signing key not found")

        if key.get("kty") == "RSA":
            signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        elif key.get("kty") == "EC":
            signing_key = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(key))
        else:
            raise OAuthVerificationError("unsupported signing key type")

        audience = settings.apple_client_id if provider == "apple" else settings.google_client_id
        if not audience:
            raise OAuthVerificationError(f"{provider.upper()}_CLIENT_ID is not configured")
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=[algorithm],
            audience=audience,
            options={"require": ["sub", "iss", "aud"]},
        )
    except (jwt.PyJWTError, httpx.HTTPError, KeyError, TypeError) as exc:
        raise OAuthVerificationError("invalid OAuth identity token") from exc

    issuer = claims.get("iss")
    allowed_issuers = ISSUERS[provider]
    if issuer not in (allowed_issuers if isinstance(allowed_issuers, set) else {allowed_issuers}):
        raise OAuthVerificationError("invalid OAuth token issuer")
    return str(claims["sub"]), claims.get("email")


async def _verify_vk(token: str) -> tuple[str, str | None]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                settings.vk_userinfo_url,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise OAuthVerificationError("VK identity verification failed") from exc

    data = body.get("user", body)
    subject = data.get("user_id") or data.get("id")
    if not subject:
        raise OAuthVerificationError("VK response has no user id")
    return str(subject), data.get("email")


async def verify_oauth_token(provider: str, id_token: str) -> tuple[str, str | None]:
    """Return a namespaced subject and trusted email, or raise a verification error."""
    if id_token.startswith("test:") and settings.env != "production":
        return f"{provider}:{id_token.removeprefix('test:')}", None
    if settings.env == "production" and id_token.startswith("test:"):
        raise OAuthVerificationError("test OAuth tokens are disabled in production")

    if provider in {"apple", "google"}:
        subject, email = await _verify_jwt(provider, id_token)
    elif provider == "vk":
        subject, email = await _verify_vk(id_token)
    else:
        raise OAuthVerificationError("unsupported provider")
    return f"{provider}:{subject}", email
