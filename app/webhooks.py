"""Outbound signed webhooks for Zapier/Make and custom endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.request
from typing import Any

from .supabase_client import get_supabase

logger = logging.getLogger(__name__)


def sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def deliver_event(user_id: str, event: str, payload: dict[str, Any]) -> int:
    sb = get_supabase()
    hooks = (
        sb.table("agency_webhooks")
        .select("*")
        .eq("user_id", user_id)
        .eq("enabled", True)
        .execute()
    ).data or []

    delivered = 0
    body = json.dumps({"event": event, "data": payload}).encode("utf-8")

    for hook in hooks:
        events = hook.get("events") or []
        if event not in events and "*" not in events:
            continue
        signature = sign_payload(hook["secret"], body)
        status_code = None
        success = False
        try:
            req = urllib.request.Request(
                hook["url"],
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Gatha-Signature": signature,
                    "X-Gatha-Event": event,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status_code = getattr(resp, "status", 200)
                success = 200 <= int(status_code) < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook %s delivery failed: %s", hook["id"],exc)
            status_code = None
            success = False

        sb.table("agency_webhook_deliveries").insert({
            "webhook_id": hook["id"],
            "event": event,
            "payload_json": {"event": event, "data": payload},
            "status_code": status_code,
            "success": success,
        }).execute()

        fail_count = int(hook.get("fail_count") or 0)
        if success:
            delivered += 1
            sb.table("agency_webhooks").update({
                "fail_count": 0,
                "last_status": status_code,
                "last_delivered_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
            }).eq("id", hook["id"]).execute()
        else:
            fail_count += 1
            update: dict[str, Any] = {
                "fail_count": fail_count,
                "last_status": status_code,
            }
            if fail_count >= 10:
                update["enabled"] = False
            sb.table("agency_webhooks").update(update).eq("id", hook["id"]).execute()

    return delivered
