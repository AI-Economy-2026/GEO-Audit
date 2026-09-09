"""Capability → provider routing with SerpAPI + DataForSEO."""

from __future__ import annotations

from typing import Optional

from .base import SerpCapability, SerpProvider
from .dataforseo import DataForSeoProvider
from .serpapi import SerpApiProvider

# Primary provider per capability (plan § capability map).
_PRIMARY: dict[SerpCapability, str] = {
    SerpCapability.ORGANIC: "dataforseo",
    SerpCapability.KEYWORD_IDEAS: "dataforseo",
    SerpCapability.BACKLINKS: "dataforseo",
    SerpCapability.LOCAL_PACK: "dataforseo",
    SerpCapability.SITE_INDEX: "serpapi",
    SerpCapability.DIRECTORY: "serpapi",
}

_FALLBACK: dict[SerpCapability, Optional[str]] = {
    SerpCapability.ORGANIC: "serpapi",
    SerpCapability.KEYWORD_IDEAS: None,
    SerpCapability.BACKLINKS: None,
    SerpCapability.LOCAL_PACK: "serpapi",
    SerpCapability.SITE_INDEX: "dataforseo",
    SerpCapability.DIRECTORY: None,
}


def _build(name: str) -> SerpProvider:
    if name == "dataforseo":
        return DataForSeoProvider()
    return SerpApiProvider()


def get_serp_provider(capability: SerpCapability | str) -> SerpProvider:
    """Return the best configured provider for a capability."""
    cap = SerpCapability(capability) if isinstance(capability, str) else capability
    primary_name = _PRIMARY[cap]
    primary = _build(primary_name)
    if primary.is_configured():
        return primary
    fallback_name = _FALLBACK.get(cap)
    if fallback_name:
        fallback = _build(fallback_name)
        if fallback.is_configured():
            return fallback
    return primary  # may be unconfigured; callers handle provider_unavailable


def provider_status() -> dict[str, bool]:
    return {
        "serpapi": SerpApiProvider().is_configured(),
        "dataforseo": DataForSeoProvider().is_configured(),
    }
