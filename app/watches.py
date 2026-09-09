"""Watch tick: schedule credit-based re-audits."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .supabase_client import execute_with_retry, get_supabase
from .worker import run_audit_task

logger = logging.getLogger(__name__)

CADENCE_DAYS = {
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
}


def _next_run(cadence: str, from_dt: datetime | None = None) -> str:
    base = from_dt or datetime.now(timezone.utc)
    days = CADENCE_DAYS.get(cadence, 30)
    return (base + timedelta(days=days)).isoformat()


def tick_due_watches(limit: int = 20) -> dict[str, Any]:
    """Find due watches, spend a credit, clone audit via re-audit pattern, start worker."""
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    due = (
        sb.table("geo_watches")
        .select("*")
        .eq("status", "active")
        .lte("next_run_at", now)
        .order("next_run_at")
        .limit(limit)
        .execute()
    )
    rows = due.data or []
    started: list[str] = []
    paused: list[str] = []
    errors: list[str] = []

    for watch in rows:
        watch_id = watch["id"]
        user_id = watch["created_by"]
        source_audit_id = watch["audit_id"]
        try:
            # Spend one audit credit
            try:
                execute_with_retry(
                    lambda: sb.rpc("spend_credit", {"p_user_id": user_id}).execute(),
                    op="spend_credit for watch",
                )
            except Exception as credit_exc:  # noqa: BLE001
                logger.warning("Watch %s paused — insufficient credits: %s", watch_id, credit_exc)
                sb.table("geo_watches").update({
                    "status": "paused",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", watch_id).execute()
                paused.append(watch_id)
                continue

            source = (
                sb.table("geo_audits")
                .select("*")
                .eq("id", source_audit_id)
                .single()
                .execute()
            ).data
            prompts = (
                sb.table("geo_audit_prompts")
                .select("prompt_id, category, prompt_text, prompt_type")
                .eq("audit_id", source_audit_id)
                .order("prompt_id")
                .execute()
            ).data or []

            insert = {
                "created_by": user_id,
                "brand_name": source["brand_name"],
                "brand_url": source["brand_url"],
                "competitors": source.get("competitors") or [],
                "engines": source.get("engines") or [],
                "keywords": source.get("keywords") or [],
                "country": source.get("country"),
                "status": "pending",
                "parent_audit_id": source_audit_id,
                "seo_addon_enabled": bool(source.get("seo_addon_enabled")),
            }
            new_audit = sb.table("geo_audits").insert(insert).execute().data[0]
            new_id = new_audit["id"]
            if prompts:
                sb.table("geo_audit_prompts").insert([
                    {
                        "audit_id": new_id,
                        "prompt_id": p["prompt_id"],
                        "category": p["category"],
                        "prompt_text": p["prompt_text"],
                        "prompt_type": p.get("prompt_type") or "ranking",
                    }
                    for p in prompts
                ]).execute()

            sb.table("geo_watches").update({
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_audit_id": new_id,
                "next_run_at": _next_run(watch.get("cadence") or "monthly"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", watch_id).execute()

            run_audit_task(new_id)
            started.append(new_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Watch tick failed for %s", watch_id)
            errors.append(f"{watch_id}:{exc}")

    return {"started": started, "paused": paused, "errors": errors, "checked": len(rows)}
