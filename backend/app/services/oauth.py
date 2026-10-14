"""External sign-in verification.

Only VK ID is supported: Russian services may authorise users by a Russian phone
number, Gosuslugi (ESIA), the Unified Biometric System or a Russian-owned
information system (149-FZ). The mobile client sends a VK ID access token; it is
verified by VK's user-info endpoint, which answers only for tokens issued to our
client_id.
"""

from __future__ import annotations

import httpx

from app.core.config import settings


class OAuthVerificationError(ValueError):
    pass


async def _verify_vk(token: str) -> tuple[str, str | None]:
    if not settings.vk_client_id:
        raise OAuthVerificationError("VK_CLIENT_ID is not configured")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.vk_userinfo_url,
                data={"access_token": token, "client_id": settings.vk_client_id},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise OAuthVerificationError("VK identity verification failed") from exc

    if body.get("error"):
        raise OAuthVerificationError("VK rejected the access token")
    data = body.get("user") or {}
    subject = data.get("user_id")
    if not subject:
        raise OAuthVerificationError("VK response has no user id")
    return str(subject), data.get("email")


async def verify_oauth_token(provider: str, id_token: str) -> tuple[str, str | None]:
    """Return a namespaced subject and trusted email, or raise a verification error."""
    if id_token.startswith("test:") and settings.env != "production":
        return f"{provider}:{id_token.removeprefix('test:')}", None
    if settings.env == "production" and id_token.startswith("test:"):
        raise OAuthVerificationError("test OAuth tokens are disabled in production")
    if provider != "vk":
        raise OAuthVerificationError("unsupported provider")
    subject, email = await _verify_vk(id_token)
    return f"{provider}:{subject}", email
