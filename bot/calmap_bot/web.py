"""HTTP side of the bot: YooKassa notifications and a health check.

A notification only tells which payment or refund changed; its body is not
trusted — the state is re-read from the YooKassa API. Answering 5xx makes YooKassa
deliver the notification again.
"""

from __future__ import annotations

import logging

from aiohttp import web

from calmap_bot.billing import Billing
from calmap_bot.yookassa import OBJECT_ID, YooKassaNotFound

logger = logging.getLogger(__name__)


def build_app(billing: Billing) -> web.Application:
    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def yookassa_webhook(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            event = str(body.get("event", ""))
            object_id = str((body.get("object") or {}).get("id", ""))
        except (ValueError, AttributeError):
            return web.json_response({"error": "bad request"}, status=400)
        # YooKassa ids are UUIDs; anything else never reaches its API.
        if not OBJECT_ID.fullmatch(object_id):
            return web.json_response({"error": "bad object id"}, status=400)
        try:
            if event.startswith("payment."):
                await billing.process_payment(object_id)
            elif event == "refund.succeeded":
                await billing.process_refund(object_id)
        except YooKassaNotFound:
            logger.warning("notification for unknown object %s ignored", object_id)
        except Exception:  # noqa: BLE001 — answer 500 so YooKassa retries
            logger.exception("YooKassa notification %s %s failed", event, object_id)
            return web.json_response({"error": "temporary"}, status=500)
        return web.json_response({"ok": True})

    app = web.Application(client_max_size=64 * 1024)
    app.router.add_get("/health", health)
    app.router.add_post("/yookassa/webhook", yookassa_webhook)
    return app
