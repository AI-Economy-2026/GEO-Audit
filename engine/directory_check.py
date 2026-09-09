"""
Directory & Citation Check
===========================
Checks whether a brand is listed on key business directories.
Uses the SERP provider factory (SerpAPI/SearchAPI).
"""

from __future__ import annotations

import logging

from engine.providers.serp import SerpCapability, get_serp_provider

logger = logging.getLogger(__name__)

DIRECTORIES = [
    {
        "name": "Google Business Profile",
        "search_template": 'site:google.com/maps "{brand}"',
    },
    {
        "name": "Yelp",
        "search_template": 'site:yelp.com "{brand}"',
    },
    {
        "name": "Trustpilot",
        "search_template": 'site:trustpilot.com "{brand}"',
    },
    {
        "name": "G2",
        "search_template": 'site:g2.com "{brand}"',
    },
    {
        "name": "Capterra",
        "search_template": 'site:capterra.com "{brand}"',
    },
    {
        "name": "Clutch",
        "search_template": 'site:clutch.co "{brand}"',
    },
    {
        "name": "LinkedIn",
        "search_template": 'site:linkedin.com/company "{brand}"',
    },
]


def check_directories(brand: str, country: str | None = None) -> list[dict]:
    """
    Check whether the brand is listed on key directories.

    Returns list of dicts: [{directory, listed, link, error}]
    """
    provider = get_serp_provider(SerpCapability.DIRECTORY)
    if not provider.is_configured():
        return [
            {
                "directory": d["name"],
                "listed": False,
                "link": None,
                "error": "SERPAPI_API_KEY not set",
            }
            for d in DIRECTORIES
        ]

    results = []
    for directory in DIRECTORIES:
        query = directory["search_template"].replace("{brand}", brand)
        try:
            data = provider.directory_search(query, country=country, num=3)
            organic = data.get("organic") or []
            if organic:
                results.append({
                    "directory": directory["name"],
                    "listed": True,
                    "link": organic[0].get("link", ""),
                    "error": None,
                })
            else:
                results.append({
                    "directory": directory["name"],
                    "listed": False,
                    "link": None,
                    "error": data.get("error"),
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Directory check failed for %s: %s", directory["name"],exc)
            results.append({
                "directory": directory["name"],
                "listed": False,
                "link": None,
                "error": str(exc)[:200],
            })

    return results
