"""In-process sliding-window rate limiting for abuse-prone public endpoints.

The counters live in the worker's memory, so with several uvicorn workers the
effective limit is multiplied by the worker count. That is acceptable for its job —
blunting password guessing and sign-up floods on a single VPS. A shared limiter
(Redis or the ingress) is the next step for a multi-host deployment.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import settings

_WINDOW_SECONDS = 60.0
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request, scope: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{scope}:{host}"


def reset() -> None:
    _hits.clear()


async def limit_auth(request: Request) -> None:
    """Dependency: at most AUTH_RATE_LIMIT_PER_MINUTE auth attempts per client IP."""
    limit = settings.auth_rate_limit_per_minute
    if limit <= 0:
        return
    now = time.monotonic()
    window = _hits[_client_key(request, "auth")]
    while window and now - window[0] > _WINDOW_SECONDS:
        window.popleft()
    if len(window) >= limit:
        retry_after = int(_WINDOW_SECONDS - (now - window[0])) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "слишком много попыток, повторите через минуту",
            headers={"Retry-After": str(retry_after)},
        )
    window.append(now)
    if len(_hits) > 50_000:  # keep memory bounded under a spray of addresses
        for key in [k for k, v in _hits.items() if not v or now - v[-1] > _WINDOW_SECONDS]:
            del _hits[key]
