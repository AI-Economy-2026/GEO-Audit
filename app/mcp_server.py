"""Gatha MCP server — exposes audit data as MCP tools for Claude.

Implements a lightweight MCP-compatible HTTP API using FastAPI's APIRouter.
Each agency gets an MCP API key (stored in agency_mcp_keys). Tool calls are
scoped to that agency's data via the user_id resolved from the API key.

Endpoints:
    GET  /mcp/tools          — list available tools (JSON)
    POST /mcp/tools/{tool}   — call a tool with arguments

Auth: Bearer token = agency MCP API key (validated against agency_mcp_keys).
"""

from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from .supabase_client import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# The public MCP endpoint URL shown to users. In production this is the
# FastAPI worker's public URL + /mcp. We fall back to a sensible default.
MCP_ENDPOINT = os.environ.get("MCP_ENDPOINT", "https://api.gatha.ai/mcp")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_audits",
        "description": "List all completed audits for the agency, ordered by most recent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max audits to return (1-100).",
                },
            },
        },
    },
    {
        "name": "get_audit_summary",
        "description": (
            "Get the full summary of a specific audit including visibility rate, "
            "engine breakdown, SEO scores, and brand details."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "audit_id": {
                    "type": "string",
                    "description": "The audit UUID.",
                },
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "get_site_health",
        "description": "Get the AI site health crawl results for an audit (from summary_json.seo.site_health).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audit_id": {"type": "string", "description": "The audit UUID."},
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "get_opportunities",
        "description": "Get content gap / keyword opportunities for an audit (from summary_json.keyword_gap_analysis).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audit_id": {"type": "string", "description": "The audit UUID."},
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "get_rankings",
        "description": "Get keyword rankings and visibility data for an audit (engine_breakdown, category_performance).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audit_id": {"type": "string", "description": "The audit UUID."},
            },
            "required": ["audit_id"],
        },
    },
    {
        "name": "compare_audits",
        "description": "Compare visibility and SEO metrics across multiple audits (markets). Pass 2-5 audit IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audit_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-5 audit IDs to compare.",
                },
            },
            "required": ["audit_ids"],
        },
    },
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _resolve_api_key(authorization: str | None) -> str:
    """Validate the Bearer token against agency_mcp_keys and return the user_id.

    Uses constant-time comparison so a wrong key cannot be recovered by timing.
    Updates last_used_at on success.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")

    provided = authorization[len("Bearer "):]

    sb = get_supabase()
    # Fetch all keys (small table, one per agency) and compare in Python.
    # This avoids sending the provided key to the database.
    result = sb.table("agency_mcp_keys").select("user_id, api_key").execute()
    rows = result.data or []

    user_id: str | None = None
    for row in rows:
        stored = row.get("api_key", "")
        if hmac.compare_digest(provided, stored):
            user_id = row.get("user_id")
            break

    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid MCP API key.")

    # Update last_used_at (best-effort, don't fail the request on error)
    try:
        sb.table("agency_mcp_keys").update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("user_id", user_id).execute()
    except Exception:
        logger.warning("Failed to update MCP key last_used_at for user %s", user_id)

    return user_id


# ---------------------------------------------------------------------------
# Tool implementations (all scoped to agency_owner_id)
# ---------------------------------------------------------------------------

def _tool_list_audits(user_id: str, limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    sb = get_supabase()
    result = (
        sb.table("geo_audits")
        .select("id, brand_name, brand_url, country, status, visibility_rate, completed_at")
        .eq("created_by", user_id)
        .eq("status", "completed")
        .order("completed_at", desc=True)
        .limit(limit)
        .execute()
    )
    audits = result.data or []
    return {
        "count": len(audits),
        "audits": audits,
    }


def _tool_get_audit_summary(user_id: str, audit_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("geo_audits")
        .select(
            "id, brand_name, brand_url, country, status, visibility_rate, "
            "total_queries, total_mentioned, engines, summary_json, completed_at"
        )
        .eq("id", audit_id)
        .eq("created_by", user_id)
        .maybeSingle()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Audit not found or not accessible.")
    return result.data


def _tool_get_site_health(user_id: str, audit_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("geo_audits")
        .select("summary_json, brand_name")
        .eq("id", audit_id)
        .eq("created_by", user_id)
        .maybeSingle()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Audit not found or not accessible.")
    summary = result.data.get("summary_json") or {}
    seo = summary.get("seo") if isinstance(summary, dict) else None
    site_health = seo.get("site_health") if isinstance(seo, dict) else None
    return {
        "audit_id": audit_id,
        "brand_name": result.data.get("brand_name"),
        "site_health": site_health or {},
    }


def _tool_get_opportunities(user_id: str, audit_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("geo_audits")
        .select("summary_json, brand_name")
        .eq("id", audit_id)
        .eq("created_by", user_id)
        .maybeSingle()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Audit not found or not accessible.")
    summary = result.data.get("summary_json") or {}
    opportunities = summary.get("keyword_gap_analysis") if isinstance(summary, dict) else None
    return {
        "audit_id": audit_id,
        "brand_name": result.data.get("brand_name"),
        "opportunities": opportunities or [],
    }


def _tool_get_rankings(user_id: str, audit_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("geo_audits")
        .select("summary_json, brand_name, visibility_rate, engines")
        .eq("id", audit_id)
        .eq("created_by", user_id)
        .maybeSingle()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Audit not found or not accessible.")
    summary = result.data.get("summary_json") or {}
    engine_breakdown = summary.get("engine_breakdown") if isinstance(summary, dict) else None
    category_performance = summary.get("category_performance") if isinstance(summary, dict) else None
    return {
        "audit_id": audit_id,
        "brand_name": result.data.get("brand_name"),
        "visibility_rate": result.data.get("visibility_rate"),
        "engines": result.data.get("engines"),
        "engine_breakdown": engine_breakdown or {},
        "category_performance": category_performance or {},
    }


def _tool_compare_audits(user_id: str, audit_ids: list[str]) -> dict[str, Any]:
    if len(audit_ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 audit IDs to compare.")
    if len(audit_ids) > 5:
        raise HTTPException(status_code=400, detail="Compare at most 5 audits at a time.")

    sb = get_supabase()
    result = (
        sb.table("geo_audits")
        .select(
            "id, brand_name, brand_url, country, visibility_rate, "
            "total_queries, total_mentioned, engines, summary_json, completed_at"
        )
        .in_("id", audit_ids)
        .eq("created_by", user_id)
        .execute()
    )
    audits = result.data or []
    if not audits:
        raise HTTPException(status_code=404, detail="No matching audits found.")

    # Build comparison structure
    comparison = []
    for audit in audits:
        summary = audit.get("summary_json") or {}
        comparison.append({
            "audit_id": audit.get("id"),
            "brand_name": audit.get("brand_name"),
            "country": audit.get("country"),
            "visibility_rate": audit.get("visibility_rate"),
            "total_queries": audit.get("total_queries"),
            "total_mentioned": audit.get("total_mentioned"),
            "engines": audit.get("engines"),
            "completed_at": audit.get("completed_at"),
            "engine_breakdown": summary.get("engine_breakdown") if isinstance(summary, dict) else None,
        })

    return {
        "count": len(comparison),
        "comparison": comparison,
    }


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/tools")
async def list_tools(authorization: str | None = Header(default=None)):
    """List all available MCP tools with their descriptions and input schemas."""
    # Validate auth so unauthenticated callers can't enumerate tools.
    _resolve_api_key(authorization)
    return {
        "tools": TOOLS,
        "endpoint": MCP_ENDPOINT,
    }


@router.post("/tools/{tool_name}")
async def call_tool(
    tool_name: str,
    body: ToolCallRequest,
    authorization: str | None = Header(default=None),
):
    """Call an MCP tool by name with the provided arguments."""
    user_id = _resolve_api_key(authorization)
    args = body.arguments or {}

    if tool_name == "list_audits":
        return _tool_list_audits(user_id, limit=args.get("limit", 20))
    elif tool_name == "get_audit_summary":
        audit_id = args.get("audit_id")
        if not audit_id:
            raise HTTPException(status_code=400, detail="audit_id is required.")
        return _tool_get_audit_summary(user_id, audit_id)
    elif tool_name == "get_site_health":
        audit_id = args.get("audit_id")
        if not audit_id:
            raise HTTPException(status_code=400, detail="audit_id is required.")
        return _tool_get_site_health(user_id, audit_id)
    elif tool_name == "get_opportunities":
        audit_id = args.get("audit_id")
        if not audit_id:
            raise HTTPException(status_code=400, detail="audit_id is required.")
        return _tool_get_opportunities(user_id, audit_id)
    elif tool_name == "get_rankings":
        audit_id = args.get("audit_id")
        if not audit_id:
            raise HTTPException(status_code=400, detail="audit_id is required.")
        return _tool_get_rankings(user_id, audit_id)
    elif tool_name == "compare_audits":
        audit_ids = args.get("audit_ids")
        if not audit_ids or not isinstance(audit_ids, list):
            raise HTTPException(status_code=400, detail="audit_ids (array) is required.")
        return _tool_compare_audits(user_id, audit_ids)
    else:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
