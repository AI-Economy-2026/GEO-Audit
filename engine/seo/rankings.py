"""Organic rankings for seed keywords / prompts."""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.providers.serp import SerpCapability, get_serp_provider
from engine.providers.serp._http import clean_domain

logger = logging.getLogger(__name__)

MAX_KEYWORDS = 25


def collect_rankings(
    keywords: list[str],
    domain: str,
    country: Optional[str] = None,
) -> dict[str, Any]:
    provider = get_serp_provider(SerpCapability.ORGANIC)
    domain_clean = clean_domain(domain)
    rows: list[dict[str, Any]] = []

    if not provider.is_configured():
        return {
            "provider": provider.name,
            "rankings": [],
            "error": "provider_unavailable",
        }

    for kw in keywords[:MAX_KEYWORDS]:
        text = (kw or "").strip()
        if not text:
            continue
        try:
            data = provider.organic_results(text, country=country, num=10)
            organic = data.get("organic") or []
            rank = None
            url = None
            for item in organic:
                link = (item.get("link") or "").lower()
                if domain_clean in link:
                    rank = item.get("position")
                    url = item.get("link")
                    break
            rows.append({
                "keyword": text,
                "organic_rank": rank,
                "organic_url": url,
                "in_top_10": rank is not None,
                "top_results": organic[:5],
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ranking collect failed for %r: %s", text,exc)
            rows.append({
                "keyword": text,
                "organic_rank": None,
                "organic_url": None,
                "in_top_10": False,
                "error": str(exc)[:200],
            })

    in_top = sum(1 for r in rows if r.get("in_top_10"))
    return {
        "provider": provider.name,
        "rankings": rows,
        "summary": {
            "keywords_checked": len(rows),
            "in_top_10": in_top,
            "coverage_pct": round((in_top / len(rows)) * 100, 1) if rows else 0,
        },
        "error": None,
    }
