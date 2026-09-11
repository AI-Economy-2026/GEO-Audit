"""Google Analytics 4 data pull module.

Reads stored OAuth tokens from Supabase, refreshes expired access tokens,
and queries the Google Analytics Admin API for property listings.
"""

from __future__ import annotations

import logging
import os
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

GA4_ACCOUNT_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
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

    Reads from ga4_connections, checks token_expires_at, refreshes if needed,
    and updates the stored token in Supabase.
    """
    sb = _get_supabase()
    result = sb.table("ga4_connections").select(
        "refresh_token_enc, access_token_enc, token_expires_at"
    ).eq("user_id", user_id).maybeSingle().execute()

    if not result.data:
        raise RuntimeError("No GA4 connection found for user")

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
        raise RuntimeError("No valid refresh token — user needs to reconnect GA4")

    token_data = _refresh_access_token(refresh_token)
    new_access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", 3600)
    new_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    # Update stored token
    sb.table("ga4_connections").update({
        "access_token_enc": new_access_token,
        "token_expires_at": new_expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()

    return new_access_token


def list_properties(user_id: str) -> dict[str, Any]:
    """List the user's GA4 properties via the Analytics Admin API.

    Calls GET https://analyticsadmin.googleapis.com/v1beta/accountSummaries
    and normalizes accountSummaries[].propertySummaries[] into
    [{ property_id, display_name }].
    """
    access_token = _get_valid_access_token(user_id)
    req = urllib.request.Request(
        GA4_ACCOUNT_SUMMARIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    properties = []
    for account in data.get("accountSummaries", []):
        for prop_summary in account.get("propertySummaries", []):
            # property is in format "properties/12345"
            property_ref = prop_summary.get("property", "")
            property_id = property_ref.split("/")[-1] if property_ref else ""
            display_name = prop_summary.get("displayName", "")
            if property_id:
                properties.append({
                    "property_id": property_id,
                    "display_name": display_name,
                })

    return {"properties": properties, "error": None}
