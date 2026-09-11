"""Backlink summary + list via DataForSEO (graceful if unavailable)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.providers.serp import SerpCapability, get_serp_provider
from engine.seo.cache import cached

logger = logging.getLogger(__name__)


def collect_backlinks(domain: str, country: Optional[str] = None) -> dict[str, Any]:
    provider = get_serp_provider(SerpCapability.BACKLINKS)
    key = f"backlinks:{provider.name}:{domain}:{country or ''}"
    summary = cached(key, 3600, lambda: provider.backlinks_summary(domain, country=country))

    links: list[dict[str, Any]] = []
    if hasattr(provider, "backlinks_list"):
        try:
            list_result = provider.backlinks_list(domain, country=country, limit=50)
            links = list_result.get("backlinks") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("backlinks_list failed for %s: %s", domain, exc)

    summary["backlink_entries"] = links
    return summary
