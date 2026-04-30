"""Supabase admin client using service role key (bypasses RLS).

Long-running audits (5-10 minutes) hit a known issue where Supabase's
HTTP/2 connection pool goes stale and the next .execute() raises
httpx.RemoteProtocolError("Server disconnected"). To handle this:

1. The client is refreshed every CLIENT_TTL_SECONDS so connections don't
   sit idle long enough to be killed by NAT / load balancers.
2. reset_supabase() forces an immediate refresh — call after a network
   error to drop the dead pool and reconnect.
3. execute_with_retry() wraps .execute() calls so transient connection
   errors auto-retry with a fresh client instead of bubbling up and
   killing the audit.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, TypeVar

from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Recreate the client every N seconds so HTTP/2 connections don't go stale.
# Supabase / proxy idle timeouts are typically 60-120s; keep this well under.
CLIENT_TTL_SECONDS = 45

_client: Client | None = None
_client_created_at: float = 0.0


def get_supabase() -> Client:
    """Return a Supabase admin client, refreshing if older than CLIENT_TTL_SECONDS."""
    global _client, _client_created_at
    now = time.time()
    if _client is None or (now - _client_created_at) > CLIENT_TTL_SECONDS:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set."
            )
        _client = create_client(url, key)
        _client_created_at = now
    return _client


def reset_supabase() -> None:
    """Drop the cached client so the next get_supabase() creates a fresh one."""
    global _client, _client_created_at
    _client = None
    _client_created_at = 0.0


T = TypeVar("T")

_TRANSIENT_MARKERS = (
    "server disconnected",
    "remote protocol",
    "connection reset",
    "connection aborted",
    "connection closed",
    "read timeout",
    "remoteprotocolerror",
)


def execute_with_retry(fn: Callable[[], T], max_retries: int = 3, op: str = "supabase op") -> T:
    """Run a Supabase call with retries on transient connection errors.

    Use it for any .execute() that lives inside a long loop (audit ingestion,
    bulk writes). Pass a no-arg lambda that performs the call:

        execute_with_retry(lambda: sb.table("x").insert(row).execute(),
                           op="insert audit result")
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — we genuinely need broad catch here
            last_exc = exc
            msg = str(exc).lower()
            transient = any(marker in msg for marker in _TRANSIENT_MARKERS)
            if not transient or attempt == max_retries:
                raise
            backoff = 0.5 * attempt
            logger.warning(
                "%s transient error (attempt %d/%d): %s — retrying in %.1fs",
                op,
                attempt,
                max_retries,
                exc,
                backoff,
            )
            reset_supabase()
            time.sleep(backoff)
    # Unreachable but keeps type checker happy
    raise last_exc  # type: ignore[misc]


__all__ = ["get_supabase", "reset_supabase", "execute_with_retry"]
