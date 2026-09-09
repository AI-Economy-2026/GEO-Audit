"""SEO orchestrator — runs modules in parallel when SEO addon is enabled."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from engine.seo.backlinks import collect_backlinks
from engine.seo.content_gap import analyse_seo_content_gaps
from engine.seo.local_pack import collect_local_pack, gbp_from_directories
from engine.seo.rankings import collect_rankings
from engine.seo.score import compute_seo_score
from engine.seo.site_health import crawl_site_health
from engine.serp_analysis import check_site_index

logger = logging.getLogger(__name__)


def run_seo_modules(
    *,
    brand_name: str,
    brand_url: str,
    competitors: list[str],
    keywords: list[str],
    country: Optional[str],
    directory_results: list[dict],
    prompt_texts: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Collect SEO signals and return summary_json.seo payload."""
    seeds = list(dict.fromkeys([*(keywords or []), *((prompt_texts or [])[:10])]))
    category_queries = seeds[:6] or [brand_name]

    results: dict[str, Any] = {}

    def _site():
        return check_site_index(brand_url, country=country)

    def _rank():
        return collect_rankings(seeds, brand_url, country=country)

    def _back():
        return collect_backlinks(brand_url, country=country)

    def _local():
        return collect_local_pack(brand_name, category_queries, country=country)

    def _health():
        try:
            return crawl_site_health(brand_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Site health crawl failed: %s",exc)
            return {"pages": [], "summary": {}, "error": str(exc)[:200]}

    def _gaps():
        return analyse_seo_content_gaps(brand_url, competitors, country=country)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_site): "site_index",
            pool.submit(_rank): "rankings",
            pool.submit(_back): "backlinks",
            pool.submit(_local): "local",
            pool.submit(_health): "site_health",
            pool.submit(_gaps): "content_gaps",
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("SEO module %s failed: %s", key,exc)
                results[key] = {"error": str(exc)[:200]}

    gbp = gbp_from_directories(directory_results)
    results["gbp"] = gbp
    results["score"] = compute_seo_score(
        site_index=results.get("site_index") or {},
        rankings=results.get("rankings") or {},
        backlinks=results.get("backlinks"),
        local=results.get("local"),
        gbp=gbp,
        health=results.get("site_health"),
        content_gaps=results.get("content_gaps"),
    )
    results["schema_version"] = 1
    return results
