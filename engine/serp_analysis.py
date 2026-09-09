"""
SERP Analysis
==============
Checks organic Google rankings for audit prompts and compares
AI visibility vs traditional SEO visibility.

HTTP goes through engine.providers.serp (SerpAPI primary for site index /
organic fallback; DataForSEO preferred for organic when configured).
"""

from __future__ import annotations

import logging
from typing import Optional

from engine.providers.serp import SerpCapability, get_serp_provider
from engine.providers.serp._http import clean_domain

logger = logging.getLogger(__name__)


def check_site_index(domain: str, country: str | None = None) -> dict:
    """
    Check how many pages are indexed for a domain.

    Returns: {indexed_count, top_pages: [{title, link}]}
    """
    provider = get_serp_provider(SerpCapability.SITE_INDEX)
    return provider.site_index(domain, country=country)


def check_organic_rankings(
    prompts: list[dict],
    domain: str,
    country: str | None = None,
) -> list[dict]:
    """
    Check Google organic rankings for each prompt.

    Returns list of: [{prompt_id, prompt_text, organic_rank, organic_url, in_top_10}]
    """
    provider = get_serp_provider(SerpCapability.ORGANIC)
    if not provider.is_configured():
        return []

    domain_clean = clean_domain(domain)
    results = []

    seen = set()
    unique_prompts = []
    for p in prompts:
        if p["prompt_id"] not in seen:
            seen.add(p["prompt_id"])
            unique_prompts.append(p)

    for prompt in unique_prompts[:20]:
        try:
            data = provider.organic_results(prompt["prompt_text"], country=country, num=10)
            organic = data.get("organic") or []
            rank = None
            found_url = None
            for r in organic:
                link = (r.get("link") or "").lower()
                if domain_clean in link:
                    rank = r.get("position") or None
                    found_url = r.get("link") or ""
                    break

            results.append({
                "prompt_id": prompt["prompt_id"],
                "prompt_text": prompt["prompt_text"],
                "organic_rank": rank,
                "organic_url": found_url,
                "in_top_10": rank is not None,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("SERP check failed for prompt %s: %s", prompt["prompt_id"], exc)
            results.append({
                "prompt_id": prompt["prompt_id"],
                "prompt_text": prompt["prompt_text"],
                "organic_rank": None,
                "organic_url": None,
                "in_top_10": False,
                "error": str(exc)[:200],
            })

    return results


def compare_ai_vs_seo(
    ai_results: list[dict],
    organic_rankings: list[dict],
) -> dict:
    """Compare AI engine visibility against organic Google rankings."""
    ai_map: dict[int, bool] = {}
    for r in ai_results:
        pid = r.get("prompt_id")
        if pid is not None:
            ai_map[pid] = ai_map.get(pid, False) or r.get("brand_mentioned", False)

    organic_map: dict[int, dict] = {}
    for r in organic_rankings:
        organic_map[r["prompt_id"]] = r

    comparisons = []
    summary = {
        "seo_strong_ai_weak": 0,
        "ai_strong_seo_weak": 0,
        "both_strong": 0,
        "both_weak": 0,
        "total_compared": 0,
    }

    all_pids = set(ai_map.keys()) | set(organic_map.keys())
    for pid in sorted(all_pids):
        ai_mentioned = ai_map.get(pid, False)
        org = organic_map.get(pid, {})
        organic_rank = org.get("organic_rank")
        in_top_10 = org.get("in_top_10", False)
        prompt_text = org.get("prompt_text", "")

        if in_top_10 and not ai_mentioned:
            gap_type = "seo_strong_ai_weak"
        elif ai_mentioned and not in_top_10:
            gap_type = "ai_strong_seo_weak"
        elif ai_mentioned and in_top_10:
            gap_type = "both_strong"
        else:
            gap_type = "both_weak"

        summary[gap_type] += 1
        summary["total_compared"] += 1

        comparisons.append({
            "prompt_id": pid,
            "prompt_text": prompt_text,
            "ai_mentioned": ai_mentioned,
            "organic_rank": organic_rank,
            "in_top_10": in_top_10,
            "gap_type": gap_type,
        })

    return {
        "comparisons": comparisons,
        "summary": summary,
    }
