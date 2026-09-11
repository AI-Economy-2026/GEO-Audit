"""Background integration sends — failure isolated from audit flow.

All sends to connected integrations (Notion, Asana, Slack, GHL) go through
``send_to_integration``, which never raises: every exception is caught,
logged, and returned as an error dict. This mirrors the pattern in
``app1/app/webhooks.py`` so a flaky third-party API can never break the
main audit flow.

Auto-send is triggered from ``worker.py`` after an audit completes, via
``_dispatch_integration_sends``, which is itself wrapped in try/except.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .supabase_client import get_supabase
from .encryption import decrypt_token

logger = logging.getLogger(__name__)

SEND_TIMEOUT = 30  # seconds — same ceiling as the GSC search-analytics call
MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def send_to_integration(service: str, audit_id: str, user_id: str) -> dict:
    """Send audit data to a connected integration. Never raises.

    Returns a dict with at least ``{"success": bool}`` and, on failure,
    ``{"error": str}``.
    """
    sb = get_supabase()

    # 1. Fetch integration config
    try:
        integration = (
            sb.table("agency_integrations")
            .select("*")
            .eq("user_id", user_id)
            .eq("service", service)
            .eq("status", "connected")
            .maybe_single()
            .execute()
        ).data
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to fetch %s integration: %s", service, exc)
        return {"success": False, "error": "Failed to fetch integration"}

    if not integration:
        return {"success": False, "error": "Integration not connected"}

    # 2. Decrypt credential
    try:
        credential = decrypt_token(integration["credential_enc"])
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to decrypt %s credential: %s", service, exc)
        _mark_error(sb, integration["id"], "Decryption failed")
        return {"success": False, "error": "Credential decryption failed"}

    # 3. Fetch audit data
    try:
        audit = (
            sb.table("geo_audits")
            .select("*, summary_json")
            .eq("id", audit_id)
            .maybe_single()
            .execute()
        ).data
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to fetch audit %s: %s", audit_id, exc)
        return {"success": False, "error": "Failed to fetch audit"}

    if not audit:
        return {"success": False, "error": "Audit not found"}

    # 4. Format + send per service
    config = integration.get("config") or {}

    try:
        if service == "notion":
            result = _send_to_notion(credential, config, audit)
        elif service == "asana":
            result = _send_to_asana(credential, config, audit)
        elif service == "slack":
            result = _send_to_slack(credential, config, audit)
        elif service == "ghl":
            result = _send_to_ghl(credential, config, audit)
        else:
            return {"success": False, "error": f"Unknown service: {service}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Integration send failed: %s -> %s", service, exc)
        result = {"success": False, "error": str(exc)[:200], "status_code": None}

    # 5. Log delivery
    try:
        sb.table("agency_integration_deliveries").insert({
            "integration_id": integration["id"],
            "audit_id": audit_id,
            "event": "manual_send",
            "payload_summary": {
                "service": service,
                "brand": audit.get("brand_name"),
            },
            "status_code": result.get("status_code"),
            "success": result["success"],
            "error_message": result.get("error"),
        }).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to log integration delivery: %s", exc)

    # 6. Update integration stats
    try:
        if result["success"]:
            sb.table("agency_integrations").update({
                "send_count": (integration.get("send_count") or 0) + 1,
                "fail_count": 0,
                "last_send_status": result.get("status_code"),
                "last_sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "connected",
                "last_error": None,
            }).eq("id", integration["id"]).execute()
        else:
            fail_count = (integration.get("fail_count") or 0) + 1
            update: dict[str, Any] = {
                "fail_count": fail_count,
                "last_send_status": result.get("status_code"),
                "last_error": result.get("error"),
            }
            if fail_count >= 10:
                update["status"] = "error"
            sb.table("agency_integrations").update(update).eq(
                "id", integration["id"]
            ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to update integration stats: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Per-service send functions
# ---------------------------------------------------------------------------


def _send_to_notion(token: str, config: dict, audit: dict) -> dict:
    """Create a page in the configured Notion database or under a page.

    The user can select either a database or a page from the dropdown.
    If it's a database, the new page is created inside it.  If it's a
    page, the new page is created as a child of it.
    """
    target_id = config.get("database_id")
    if not target_id:
        return {"success": False, "error": "No Notion target selected"}

    target_type = config.get("target_type", "database")
    summary = audit.get("summary_json") or {}
    visibility = (
        summary.get("overall_visibility", {}).get("visibility_rate_percent", 0)
    )
    seo_score = 0
    try:
        seo_score = summary.get("seo", {}).get("score", {}).get("overall", 0)
    except Exception:
        pass

    brand_name = audit.get("brand_name", "Unknown")
    audit_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"Gatha Audit — {brand_name} — {audit_date}"

    # Build a few content blocks: KPI summary + pillar scores
    children = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "KPI Summary"}}]
            },
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": (
                                f"Visibility: {visibility}%\n"
                                f"SEO Score: {seo_score}/100\n"
                                f"Total Queries: "
                                f"{summary.get('audit_metadata', {}).get('total_queries', 0)}"
                            )
                        },
                    }
                ]
            },
        },
    ]

    # Top cited domains as a bullet list
    for domain_info in (summary.get("top_cited_domains") or [])[:5]:
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": (
                                f"{domain_info.get('domain')} — "
                                f"{domain_info.get('share_percent', 0)}% "
                                f"({domain_info.get('count', 0)} citations)"
                            )
                        },
                    }
                ]
            },
        })

    # Parent changes depending on whether the target is a database or a page.
    if target_type == "page":
        parent = {"page_id": target_id}
    else:
        parent = {"database_id": target_id}

    payload: dict[str, Any] = {
        "parent": parent,
        "properties": {
            "title": [{"text": {"content": title}}],
        },
        "children": children,
    }

    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=SEND_TIMEOUT) as resp:
        status = getattr(resp, "status", 200)
        return {"success": 200 <= status < 300, "status_code": status}


def _send_to_asana(token: str, config: dict, audit: dict) -> dict:
    """Create tasks in the configured Asana project from action-plan items."""
    project_id = config.get("project_id")
    if not project_id:
        return {"success": False, "error": "No Asana project selected"}

    summary = audit.get("summary_json") or {}
    action_plan = summary.get("action_plan", [])
    if not action_plan:
        # Fall back to top opportunities / keyword gaps if no action plan
        action_plan = _build_action_plan_from_summary(summary)

    if not action_plan:
        return {"success": False, "error": "No action items to send"}

    success_count = 0

    for item in action_plan:
        title = item.get("title") or item.get("name") or "Untitled action item"
        notes_parts = []
        if item.get("effort"):
            notes_parts.append(f"Effort: {item['effort']}")
        if item.get("impact"):
            notes_parts.append(f"Impact: {item['impact']}")
        if item.get("prompts_unlocked"):
            notes_parts.append(f"Prompts: {item['prompts_unlocked']}")
        if item.get("description"):
            notes_parts.append(item["description"])

        payload = {
            "data": {
                "name": title[:255],
                "notes": "\n".join(notes_parts) or "Created by Gatha Audit",
                "projects": [project_id],
            }
        }
        req = urllib.request.Request(
            "https://app.asana.com/api/1.0/tasks",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=SEND_TIMEOUT) as resp:
                status = getattr(resp, "status", 200)
                if 200 <= status < 300:
                    success_count += 1
        except Exception as exc:  # noqa: BLE001
            # Continue creating other tasks even if one fails
            logger.warning("Asana task creation failed for '%s': %s", title, exc)

    return {
        "success": success_count > 0,
        "status_code": 200,
        "tasks_created": success_count,
    }


def _send_to_slack(webhook_url: str, config: dict, audit: dict) -> dict:
    """Post a formatted message to a Slack incoming-webhook URL."""
    if not webhook_url:
        return {"success": False, "error": "No Slack webhook URL configured"}

    summary = audit.get("summary_json") or {}
    visibility = (
        summary.get("overall_visibility", {}).get("visibility_rate_percent", 0)
    )
    seo_score = 0
    try:
        seo_score = summary.get("seo", {}).get("score", {}).get("overall", 0)
    except Exception:
        pass

    brand_name = audit.get("brand_name", "Unknown")
    dashboard_url = audit.get("dashboard_url", "")

    # Top 3 opportunities
    action_plan = summary.get("action_plan", []) or _build_action_plan_from_summary(summary)
    top_ops = action_plan[:3]
    opp_lines = ""
    if top_ops:
        opp_lines = "\n*Top Opportunities:*\n"
        for i, op in enumerate(top_ops, 1):
            opp_lines += f"  {i}. {op.get('title', op.get('name', '—'))}\n"

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🔍 Gatha Audit — {brand_name}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Visibility:* {visibility}%\n"
                        f"*SEO Score:* {seo_score}/100\n"
                        f"*Total Queries:* "
                        f"{summary.get('audit_metadata', {}).get('total_queries', 0)}"
                        f"{opp_lines}"
                    ),
                },
            },
        ]
    }

    if dashboard_url:
        payload["blocks"].append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Dashboard"},
                    "url": dashboard_url,
                }
            ],
        })

    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=SEND_TIMEOUT) as resp:
        status = getattr(resp, "status", 200)
        return {"success": status == 200, "status_code": status}


def _send_to_ghl(api_key: str, config: dict, audit: dict) -> dict:
    """Search for a GHL contact by brand name, then add an audit-summary note."""
    summary = audit.get("summary_json") or {}
    visibility = (
        summary.get("overall_visibility", {}).get("visibility_rate_percent", 0)
    )
    seo_score = 0
    try:
        seo_score = summary.get("seo", {}).get("score", {}).get("overall", 0)
    except Exception:
        pass

    brand_name = audit.get("brand_name", "Unknown")
    dashboard_url = audit.get("dashboard_url", "")

    note_text = (
        f"Gatha Audit Complete — {brand_name}\n"
        f"Visibility: {visibility}%\n"
        f"SEO Score: {seo_score}/100\n"
        f"Total Queries: {summary.get('audit_metadata', {}).get('total_queries', 0)}\n"
        f"Dashboard: {dashboard_url}"
    )

    # 1. Search for an existing contact by brand name
    query = urllib.parse.urlencode({"query": brand_name})
    search_req = urllib.request.Request(
        f"https://rest.gohighlevel.com/v1/contacts?{query}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )

    contact_id = None
    try:
        with urllib.request.urlopen(search_req, timeout=SEND_TIMEOUT) as resp:
            search_data = json.loads(resp.read().decode("utf-8"))
        contacts = search_data.get("contacts") or []
        if contacts:
            contact_id = contacts[0].get("id")
    except Exception as exc:  # noqa: BLE001
        logger.warning("GHL contact search failed for '%s': %s", brand_name, exc)

    # 2. If no contact found, create one
    if not contact_id:
        create_payload = {
            "firstName": brand_name,
            "name": brand_name,
            "source": "Gatha Audit",
        }
        create_req = urllib.request.Request(
            "https://rest.gohighlevel.com/v1/contacts",
            data=json.dumps(create_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(create_req, timeout=SEND_TIMEOUT) as resp:
                create_data = json.loads(resp.read().decode("utf-8"))
            contact_id = (
                create_data.get("contact", {}).get("id")
                or create_data.get("id")
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("GHL contact creation failed for '%s': %s", brand_name, exc)
            return {"success": False, "error": "Could not find or create GHL contact"}

    # 3. Add note to the contact
    note_payload = {"body": note_text}
    note_req = urllib.request.Request(
        f"https://rest.gohighlevel.com/v1/contacts/{contact_id}/notes",
        data=json.dumps(note_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(note_req, timeout=SEND_TIMEOUT) as resp:
        status = getattr(resp, "status", 200)
        return {"success": 200 <= status < 300, "status_code": status}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_action_plan_from_summary(summary: dict) -> list[dict]:
    """Derive a simple action plan from keyword gaps when none exists."""
    items: list[dict] = []
    gaps = summary.get("keyword_gap_analysis") or {}
    for gap in (gaps.get("gaps") or [])[:10]:
        items.append({
            "title": f"Target keyword gap: {gap.get('keyword', gap.get('term', '—'))}",
            "effort": gap.get("effort", "medium"),
            "impact": gap.get("impact", "medium"),
            "prompts_unlocked": "",
            "description": gap.get("recommendation", ""),
        })
    return items


def _mark_error(sb, integration_id: str, error: str) -> None:
    """Mark an integration as in error state."""
    try:
        sb.table("agency_integrations").update({
            "status": "error",
            "last_error": error[:500],
        }).eq("id", integration_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to mark integration %s as error: %s", integration_id, exc)


def _dispatch_integration_sends(user_id: str, audit_id: str, summary: dict) -> None:
    """Send to all integrations with auto_send enabled. Failure isolated.

    Called from ``worker.py`` after an audit completes. Each individual send
    is wrapped in try/except so one broken integration cannot prevent the
    others from sending.
    """
    if not user_id:
        return

    sb = get_supabase()
    try:
        integrations = (
            sb.table("agency_integrations")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "connected")
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to fetch integrations for auto-send: %s", exc)
        return

    for integ in integrations:
        config = integ.get("config") or {}
        if not config.get("auto_send"):
            continue
        try:
            send_to_integration(integ["service"], audit_id, user_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Auto-send to %s failed: %s", integ["service"], exc)


__all__ = [
    "send_to_integration",
    "_dispatch_integration_sends",
    "_mark_error",
]
