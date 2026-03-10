"""
SERP Analysis
==============
Checks organic Google rankings for audit prompts and compares
AI visibility vs traditional SEO visibility.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


def check_site_index(domain: str) -> dict:
    """
    Check how many pages are indexed for a domain via SerpAPI.

    Returns: {indexed_count, top_pages: [{title, link}]}
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return {"indexed_count": 0, "top_pages": [], "error": "SERPAPI_API_KEY not set"}

    # Clean domain
    domain = domain.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")

    try:
        params = urllib.parse.urlencode({
            "engine": "google",
            "q": f"site:{domain}",
            "api_key": api_key,
            "num": 10,
        })
        url = f"https://serpapi.com/search.json?{params}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Get total results count
        search_info = data.get("search_information", {})
        total_str = search_info.get("total_results", "0")
        try:
            indexed_count = int(str(total_str).replace(",", ""))
        except (ValueError, TypeError):
            indexed_count = 0

        # Get top pages
        organic = data.get("organic_results", [])
        top_pages = [
            {"title": r.get("title", ""), "link": r.get("link", "")}
            for r in organic[:10]
        ]

        return {
            "indexed_count": indexed_count,
            "top_pages": top_pages,
            "error": None,
        }
    except Exception as exc:
        logger.warning(f"Site index check failed for {domain}: {exc}")
        return {"indexed_count": 0, "top_pages": [], "error": str(exc)[:200]}


def check_organic_rankings(
    prompts: list[dict],
    domain: str,
) -> list[dict]:
    """
    Check Google organic rankings for each prompt.

    Args:
        prompts: list of dicts with prompt_id and prompt_text
        domain: the brand's domain to search for

    Returns list of: [{prompt_id, prompt_text, organic_rank, organic_url, in_top_10}]
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return []

    domain_clean = domain.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
    results = []

    # Deduplicate prompts by prompt_id
    seen = set()
    unique_prompts = []
    for p in prompts:
        if p["prompt_id"] not in seen:
            seen.add(p["prompt_id"])
            unique_prompts.append(p)

    for prompt in unique_prompts[:20]:  # Cap at 20 SerpAPI calls
        try:
            params = urllib.parse.urlencode({
                "engine": "google",
                "q": prompt["prompt_text"],
                "api_key": api_key,
                "num": 10,
            })
            url = f"https://serpapi.com/search.json?{params}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            organic = data.get("organic_results", [])
            rank = None
            found_url = None
            for i, r in enumerate(organic):
                link = r.get("link", "").lower()
                if domain_clean in link:
                    rank = i + 1
                    found_url = r.get("link", "")
                    break

            results.append({
                "prompt_id": prompt["prompt_id"],
                "prompt_text": prompt["prompt_text"],
                "organic_rank": rank,
                "organic_url": found_url,
                "in_top_10": rank is not None,
            })
        except Exception as exc:
            logger.warning(f"SERP check failed for prompt {prompt['prompt_id']}: {exc}")
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
    """
    Compare AI engine visibility against organic Google rankings.

    Returns:
        {
            comparisons: [{prompt_id, prompt_text, ai_mentioned, organic_rank, gap_type}],
            summary: {seo_strong_ai_weak, ai_strong_seo_weak, both_strong, both_weak,
                       total_compared}
        }
    """
    # Build maps
    ai_map: dict[int, bool] = {}
    for r in ai_results:
        pid = r.get("prompt_id")
        if pid is not None:
            # A prompt is "ai_mentioned" if it's mentioned in ANY engine
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
