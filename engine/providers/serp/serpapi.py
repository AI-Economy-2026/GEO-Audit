"""SerpAPI/SearchAPI adapter (existing GEO search path)."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from engine.geo_locale import locale_for

from ._http import clean_domain, encode_query, get_json

logger = logging.getLogger(__name__)

SEARCHAPI_BASE = "https://www.searchapi.io/api/v1/search"


class SerpApiProvider:
    name = "serpapi"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("SERPAPI_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _locale_params(self, country: Optional[str]) -> dict[str, str]:
        loc = locale_for(country)
        if not loc:
            return {}
        return {"gl": loc["gl"], "hl": loc["hl"]}

    def _search(self, query: str, country: Optional[str] = None, num: int = 10) -> dict[str, Any]:
        if not self._api_key:
            return {"error": "SERPAPI_API_KEY not set", "organic_results": []}
        params = {
            "engine": "google",
            "q": query,
            "api_key": self._api_key,
            "num": num,
            **self._locale_params(country),
        }
        url = f"{SEARCHAPI_BASE}?{encode_query(params)}"
        try:
            return get_json(url, timeout=15)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SerpAPI search failed for %r: %s", query[:80], exc)
            return {"error": str(exc)[:200], "organic_results": []}

    def site_index(self, domain: str, country: Optional[str] = None) -> dict[str, Any]:
        domain = clean_domain(domain)
        if not self._api_key:
            return {"indexed_count": 0, "top_pages": [], "error": "SERPAPI_API_KEY not set"}
        data = self._search(f"site:{domain}", country=country, num=10)
        if data.get("error") and not data.get("organic_results"):
            return {"indexed_count": 0, "top_pages": [], "error": data.get("error")}
        search_info = data.get("search_information", {})
        total_str = search_info.get("total_results", "0")
        try:
            indexed_count = int(str(total_str).replace(",", ""))
        except (ValueError, TypeError):
            indexed_count = 0
        organic = data.get("organic_results", []) or []
        top_pages = [{"title": r.get("title", ""), "link": r.get("link", "")} for r in organic[:10]]
        return {"indexed_count": indexed_count, "top_pages": top_pages, "error": None}

    def organic_results(
        self,
        query: str,
        country: Optional[str] = None,
        num: int = 10,
    ) -> dict[str, Any]:
        data = self._search(query, country=country, num=num)
        organic = data.get("organic_results", []) or []
        return {
            "provider": self.name,
            "query": query,
            "organic": [
                {
                    "position": i + 1,
                    "title": r.get("title", ""),
                    "link": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                }
                for i, r in enumerate(organic)
            ],
            "local_results": data.get("local_results") or data.get("local_pack") or [],
            "error": data.get("error"),
        }

    def keyword_ideas(
        self,
        domain: str,
        country: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return {
            "provider": self.name,
            "keywords": [],
            "error": "provider_unavailable",
            "message": "Keyword ideas require DataForSEO",
        }

    def backlinks_summary(
        self,
        domain: str,
        country: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "provider": self.name,
            "error": "provider_unavailable",
            "message": "Backlinks require DataForSEO",
        }

    def local_pack(
        self,
        query: str,
        country: Optional[str] = None,
    ) -> dict[str, Any]:
        data = self.organic_results(query, country=country, num=10)
        local = data.get("local_results") or []
        # SearchAPI sometimes nests local pack under local_results.places
        if isinstance(local, dict):
            places = local.get("places") or local.get("results") or []
        else:
            places = local
        return {
            "provider": self.name,
            "query": query,
            "places": places if isinstance(places, list) else [],
            "error": data.get("error"),
        }

    def directory_search(
        self,
        query: str,
        country: Optional[str] = None,
        num: int = 3,
    ) -> dict[str, Any]:
        data = self._search(query, country=country, num=num)
        organic = data.get("organic_results", []) or []
        return {
            "provider": self.name,
            "organic": organic,
            "error": data.get("error"),
        }
