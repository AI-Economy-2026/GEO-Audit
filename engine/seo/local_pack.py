"""Local map-pack + GBP presence helpers."""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.providers.serp import SerpCapability, get_serp_provider

logger = logging.getLogger(__name__)


def collect_local_pack(
    brand: str,
    category_queries: list[str],
    country: Optional[str] = None,
) -> dict[str, Any]:
    provider = get_serp_provider(SerpCapability.LOCAL_PACK)
    brand_l = brand.lower().strip()
    queries = [q for q in category_queries if q.strip()][:8]
    if brand and brand not in queries:
        queries = [brand, *queries]

    packs: list[dict[str, Any]] = []
    brand_in_pack = 0

    if not provider.is_configured():
        return {
            "provider": provider.name,
            "packs": [],
            "summary": {"queries": 0, "brand_in_pack": 0, "share_pct": 0},
            "error": "provider_unavailable",
        }

    for query in queries:
        try:
            data = provider.local_pack(query, country=country)
            places = data.get("places") or []
            present = any(brand_l in (p.get("title") or "").lower() for p in places)
            if present:
                brand_in_pack += 1
            packs.append({
                "query": query,
                "brand_present": present,
                "places": places[:5],
                "error": data.get("error"),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Local pack failed for %r: %s", query,exc)
            packs.append({
                "query": query,
                "brand_present": False,
                "places": [],
                "error": str(exc)[:200],
            })

    total = len(packs)
    return {
        "provider": provider.name,
        "packs": packs,
        "summary": {
            "queries": total,
            "brand_in_pack": brand_in_pack,
            "share_pct": round((brand_in_pack / total) * 100, 1) if total else 0,
        },
        "error": None,
    }


def gbp_from_directories(directory_results: list[dict]) -> dict[str, Any]:
    for row in directory_results or []:
        if row.get("directory") == "Google Business Profile":
            return {
                "listed": bool(row.get("listed")),
                "link": row.get("link"),
                "error": row.get("error"),
            }
    return {"listed": False, "link": None, "error": None}
