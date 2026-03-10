"""
Directory & Citation Check
===========================
Checks whether a brand is listed on key business directories.
Uses SerpAPI site-specific searches as a reliable fallback.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

DIRECTORIES = [
    {
        "name": "Google Business Profile",
        "search_template": "site:google.com/maps \"{brand}\"",
    },
    {
        "name": "Yelp",
        "search_template": "site:yelp.com \"{brand}\"",
    },
    {
        "name": "Trustpilot",
        "search_template": "site:trustpilot.com \"{brand}\"",
    },
    {
        "name": "G2",
        "search_template": "site:g2.com \"{brand}\"",
    },
    {
        "name": "Capterra",
        "search_template": "site:capterra.com \"{brand}\"",
    },
    {
        "name": "Clutch",
        "search_template": "site:clutch.co \"{brand}\"",
    },
    {
        "name": "LinkedIn",
        "search_template": "site:linkedin.com/company \"{brand}\"",
    },
]


def check_directories(brand: str) -> list[dict]:
    """
    Check whether the brand is listed on key directories via SerpAPI.

    Returns list of dicts: [{directory, listed, link, error}]
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return [
            {"directory": d["name"], "listed": False, "link": None, "error": "SERPAPI_API_KEY not set"}
            for d in DIRECTORIES
        ]

    results = []
    for directory in DIRECTORIES:
        query = directory["search_template"].replace("{brand}", brand)
        try:
            params = urllib.parse.urlencode({
                "engine": "google",
                "q": query,
                "api_key": api_key,
                "num": 3,
            })
            url = f"https://serpapi.com/search.json?{params}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            organic = data.get("organic_results", [])
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
                    "error": None,
                })
        except Exception as exc:
            logger.warning(f"Directory check failed for {directory['name']}: {exc}")
            results.append({
                "directory": directory["name"],
                "listed": False,
                "link": None,
                "error": str(exc)[:200],
            })

    return results
