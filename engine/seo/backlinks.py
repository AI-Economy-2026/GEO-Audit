"""Backlink summary via DataForSEO (graceful if unavailable)."""

from __future__ import annotations

from typing import Any, Optional

from engine.providers.serp import SerpCapability, get_serp_provider
from engine.seo.cache import cached


def collect_backlinks(domain: str, country: Optional[str] = None) -> dict[str, Any]:
    provider = get_serp_provider(SerpCapability.BACKLINKS)
    key = f"backlinks:{provider.name}:{domain}:{country or ''}"
    return cached(key, 3600, lambda: provider.backlinks_summary(domain, country=country))
