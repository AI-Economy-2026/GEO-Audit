"""Google Search Console data pull module.

Reads stored OAuth tokens from Supabase, refreshes expired access tokens,
and queries the Search Console API for search analytics.
"""

from __future__ import annotations

import logging
import os
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

GSC_SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
GSC_SEARCH_ANALYTICS_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"


def _get_supabase():
    from .supabase_client import get_supabase
    return get_supabase()


def _refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Exchange a refresh token for a new access token."""
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID/SECRET not configured")

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(
        TOKEN_REFRESH_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        token_data = json.loads(resp.read().decode())
    return token_data  # contains access_token, expires_in, etc.


def _get_valid_access_token(user_id: str) -> str:
    """Get a valid access token for the user, refreshing if expired.

    Reads from gsc_connections, checks token_expires_at, refreshes if needed,
    and updates the stored token in Supabase.
    """
    sb = _get_supabase()
    result = sb.table("gsc_connections").select(
        "refresh_token_enc, access_token_enc, token_expires_at"
    ).eq("user_id", user_id).maybe_single().execute()

    if not result.data:
        raise RuntimeError("No GSC connection found for user")

    conn = result.data
    refresh_token = conn.get("refresh_token_enc", "")
    access_token = conn.get("access_token_enc", "")
    expires_at = conn.get("token_expires_at")

    # Check if current access token is still valid (with 5 min buffer)
    if access_token and expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp > datetime.now(timezone.utc) + timedelta(minutes=5):
                return access_token
        except Exception:
            pass  # fall through to refresh

    # Token expired or missing — refresh
    if not refresh_token or refresh_token.startswith("pending:") or refresh_token.startswith("stub:"):
        raise RuntimeError("No valid refresh token — user needs to reconnect GSC")

    token_data = _refresh_access_token(refresh_token)
    new_access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", 3600)
    new_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    # Update stored token
    sb.table("gsc_connections").update({
        "access_token_enc": new_access_token,
        "token_expires_at": new_expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()

    return new_access_token


def list_sites(user_id: str) -> dict[str, Any]:
    """List the user's GSC properties (sites)."""
    access_token = _get_valid_access_token(user_id)
    req = urllib.request.Request(
        GSC_SITES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    sites = []
    for site in data.get("siteEntry", []):
        sites.append({
            "url": site.get("siteUrl", ""),
            "permission_level": site.get("permissionLevel", ""),
        })
    return {"sites": sites, "error": None}


def query_search_analytics(
    user_id: str,
    site_url: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    row_limit: int = 100,
) -> dict[str, Any]:
    """Query GSC Search Analytics for clicks, impressions, CTR, position by query.

    Returns top queries with metrics + a summary.
    """
    access_token = _get_valid_access_token(user_id)

    # Default to last 28 days
    if not end_date:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now(timezone.utc) - timedelta(days=28)).strftime("%Y-%m-%d")

    # URL-encode the site URL for the path
    encoded_site = urllib.parse.quote(site_url, safe="")
    url = GSC_SEARCH_ANALYTICS_URL.format(site=encoded_site)

    payload = json.dumps({
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query"],
        "rowLimit": min(row_limit, 1000),
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    rows = data.get("rows", [])
    queries = []
    total_clicks = 0
    total_impressions = 0
    total_ctr = 0
    total_position = 0

    for row in rows:
        clicks = row.get("clicks", 0)
        impressions = row.get("impressions", 0)
        ctr = row.get("ctr", 0)
        position = row.get("position", 0)
        total_clicks += clicks
        total_impressions += impressions
        total_ctr += ctr
        total_position += position
        queries.append({
            "query": row.get("keys", [""])[0] if row.get("keys") else "",
            "clicks": clicks,
            "impressions": impressions,
            "ctr": round(ctr * 100, 2),  # convert to percentage
            "position": round(position, 1),
        })

    # Sort by clicks descending
    queries.sort(key=lambda q: q["clicks"], reverse=True)

    summary = {
        "total_clicks": total_clicks,
        "total_impressions": total_impressions,
        "avg_ctr": round((total_ctr / len(rows)) * 100, 2) if rows else 0,
        "avg_position": round(total_position / len(rows), 1) if rows else 0,
        "total_queries": len(queries),
        "date_range": f"{start_date} to {end_date}",
    }

    return {
        "queries": queries[:row_limit],
        "summary": summary,
        "error": None,
    }
