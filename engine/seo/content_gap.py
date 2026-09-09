"""SEO content gap: organic keywords competitors rank for that brand does not."""

from __future__ import annotations

from typing import Any, Optional

from engine.providers.serp import SerpCapability, get_serp_provider
from engine.providers.serp._http import clean_domain


def analyse_seo_content_gaps(
    brand_url: str,
    competitors: list[str],
    country: Optional[str] = None,
    limit: int = 30,
) -> dict[str, Any]:
    """
    Competitors here are treated as domain-ish strings when possible.
    If a competitor looks like a name (no dot), it is skipped for DFS target.
    """
    provider = get_serp_provider(SerpCapability.KEYWORD_IDEAS)
    if not provider.is_configured():
        return {
            "gaps": [],
            "error": "provider_unavailable",
            "message": "SEO content gaps require DataForSEO",
        }

    brand_domain = clean_domain(brand_url)
    brand_kw = provider.keyword_ideas(brand_domain, country=country, limit=limit)
    brand_set = {
        (k.get("keyword") or "").lower()
        for k in (brand_kw.get("keywords") or [])
        if k.get("keyword")
    }

    gaps: list[dict[str, Any]] = []
    for comp in competitors[:5]:
        target = comp.strip()
        if "." not in target:
            # Not a domain — cannot query ranked keywords reliably
            continue
        comp_domain = clean_domain(target)
        data = provider.keyword_ideas(comp_domain, country=country, limit=limit)
        for item in data.get("keywords") or []:
            kw = (item.get("keyword") or "").strip()
            if not kw or kw.lower() in brand_set:
                continue
            gaps.append({
                "keyword": kw,
                "competitor": comp_domain,
                "volume": item.get("volume"),
                "difficulty": item.get("difficulty"),
            })

    gaps.sort(key=lambda g: (g.get("volume") or 0), reverse=True)
    return {
        "gaps": gaps[:50],
        "brand_keyword_count": len(brand_set),
        "error": None,
    }
