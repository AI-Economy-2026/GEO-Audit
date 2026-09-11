"""DataForSEO adapter. Degrades gracefully when credentials are missing."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Optional

from ._http import clean_domain, post_json

logger = logging.getLogger(__name__)

DFS_BASE = "https://api.dataforseo.com/v3"


class DataForSeoProvider:
    name = "dataforseo"

    def __init__(
        self,
        login: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self._login = login if login is not None else os.getenv("DATAFORSEO_LOGIN", "")
        self._password = password if password is not None else os.getenv("DATAFORSEO_PASSWORD", "")

    def is_configured(self) -> bool:
        return bool(self._login and self._password)

    def _auth_header(self) -> dict[str, str]:
        token = base64.b64encode(f"{self._login}:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _unavailable(self, capability: str) -> dict[str, Any]:
        return {
            "provider": self.name,
            "error": "provider_unavailable",
            "message": f"DataForSEO not configured for {capability}",
        }

    def _post(self, path: str, payload: list[dict[str, Any]]) -> Any:
        if not self.is_configured():
            raise RuntimeError("DATAFORSEO credentials not set")
        url = f"{DFS_BASE}{path}"
        return post_json(url, payload, headers=self._auth_header(), timeout=45)

    def site_index(self, domain: str, country: Optional[str] = None) -> dict[str, Any]:
        # Prefer SerpAPI for site: queries; DFS can estimate via ranked keywords count.
        if not self.is_configured():
            return {**self._unavailable("site_index"), "indexed_count": 0, "top_pages": []}
        domain = clean_domain(domain)
        try:
            raw = self._post(
                "/dataforseo_labs/google/ranked_keywords/live",
                [{"target": domain, "limit": 10, "order_by": ["keyword_data.keyword_info.search_volume,desc"]}],
            )
            tasks = (raw or {}).get("tasks") or []
            result = ((tasks[0] or {}).get("result") or [{}])[0] if tasks else {}
            items = result.get("items") or []
            total = result.get("total_count") or len(items)
            top_pages = []
            for item in items[:10]:
                kw = (item.get("keyword_data") or {}).get("keyword") or ""
                serps = item.get("ranked_serp_element") or {}
                serp = serps.get("serp_item") or {}
                top_pages.append({"title": kw, "link": serp.get("url") or ""})
            return {"indexed_count": int(total or 0), "top_pages": top_pages, "error": None}
        except Exception as exc:  # noqa: BLE001
            logger.warning("DataForSEO site_index failed: %s", exc)
            return {"indexed_count": 0, "top_pages": [], "error": str(exc)[:200]}

    def organic_results(
        self,
        query: str,
        country: Optional[str] = None,
        num: int = 10,
    ) -> dict[str, Any]:
        if not self.is_configured():
            return {**self._unavailable("organic"), "organic": []}
        location_name = _location_name(country)
        try:
            raw = self._post(
                "/serp/google/organic/live/advanced",
                [{
                    "keyword": query,
                    "location_name": location_name,
                    "language_code": "en",
                    "depth": num,
                }],
            )
            tasks = (raw or {}).get("tasks") or []
            items = ((tasks[0] or {}).get("result") or [{}])[0].get("items") or []
            organic = []
            for item in items:
                if item.get("type") != "organic":
                    continue
                organic.append({
                    "position": item.get("rank_group") or item.get("rank_absolute") or len(organic) + 1,
                    "title": item.get("title") or "",
                    "link": item.get("url") or "",
                    "snippet": item.get("description") or "",
                })
            return {"provider": self.name, "query": query, "organic": organic[:num], "error": None}
        except Exception as exc:  # noqa: BLE001
            logger.warning("DataForSEO organic failed: %s", exc)
            return {"provider": self.name, "query": query, "organic": [], "error": str(exc)[:200]}

    def keyword_ideas(
        self,
        domain: str,
        country: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not self.is_configured():
            return {**self._unavailable("keyword_ideas"), "keywords": []}
        domain = clean_domain(domain)
        try:
            raw = self._post(
                "/dataforseo_labs/google/ranked_keywords/live",
                [{
                    "target": domain,
                    "limit": min(limit, 100),
                    "order_by": ["keyword_data.keyword_info.search_volume,desc"],
                }],
            )
            tasks = (raw or {}).get("tasks") or []
            items = ((tasks[0] or {}).get("result") or [{}])[0].get("items") or []
            keywords = []
            for item in items:
                kd = item.get("keyword_data") or {}
                info = kd.get("keyword_info") or {}
                keywords.append({
                    "keyword": kd.get("keyword") or "",
                    "volume": info.get("search_volume"),
                    "difficulty": (kd.get("keyword_properties") or {}).get("keyword_difficulty"),
                    "cpc": info.get("cpc"),
                })
            return {"provider": self.name, "keywords": keywords, "error": None}
        except Exception as exc:  # noqa: BLE001
            logger.warning("DataForSEO keyword_ideas failed: %s",exc)
            return {"provider": self.name, "keywords": [], "error": str(exc)[:200]}

    def backlinks_summary(
        self,
        domain: str,
        country: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.is_configured():
            return self._unavailable("backlinks")
        domain = clean_domain(domain)
        try:
            raw = self._post(
                "/backlinks/summary/live",
                [{"target": domain, "include_subdomains": True}],
            )
            tasks = (raw or {}).get("tasks") or []
            result = ((tasks[0] or {}).get("result") or [{}])[0] if tasks else {}
            return {
                "provider": self.name,
                "domain": domain,
                "referring_domains": result.get("referring_domains") or 0,
                "backlinks": result.get("backlinks") or 0,
                "broken_backlinks": result.get("broken_backlinks") or 0,
                "referring_main_domains": result.get("referring_main_domains") or 0,
                "rank": result.get("rank"),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("DataForSEO backlinks failed: %s",exc)
            return {"provider": self.name, "error": str(exc)[:200]}

    def backlinks_list(
        self,
        domain: str,
        country: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not self.is_configured():
            return self._unavailable("backlinks_list")
        domain = clean_domain(domain)
        try:
            raw = self._post(
                "/backlinks/backend/live",
                [{
                    "target": domain,
                    "include_subdomains": True,
                    "limit": min(limit, 100),
                    "order_by": ["domain_from_rank,desc"],
                }],
            )
            tasks = (raw or {}).get("tasks") or []
            result = ((tasks[0] or {}).get("result") or [{}])[0] if tasks else {}
            items = result.get("items") or []
            links = []
            for item in items:
                links.append({
                    "source_url": item.get("url_from") or "",
                    "source_domain": item.get("domain_from") or "",
                    "target_url": item.get("url_to") or "",
                    "anchor": item.get("anchor") or "",
                    "domain_rank": item.get("domain_from_rank"),
                    "page_rank": item.get("page_from_rank"),
                    "first_seen": item.get("first_seen"),
                    "is_lost": item.get("is_lost"),
                })
            return {"provider": self.name, "backlinks": links, "error": None}
        except Exception as exc:  # noqa: BLE001
            logger.warning("DataForSEO backlinks_list failed: %s", exc)
            return {"provider": self.name, "backlinks": [], "error": str(exc)[:200]}

    def local_pack(
        self,
        query: str,
        country: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.is_configured():
            return {**self._unavailable("local_pack"), "places": []}
        location_name = _location_name(country)
        try:
            raw = self._post(
                "/serp/google/organic/live/advanced",
                [{
                    "keyword": query,
                    "location_name": location_name,
                    "language_code": "en",
                    "depth": 20,
                }],
            )
            tasks = (raw or {}).get("tasks") or []
            items = ((tasks[0] or {}).get("result") or [{}])[0].get("items") or []
            places = []
            for item in items:
                if item.get("type") not in ("local_pack", "map", "local_services"):
                    continue
                for place in item.get("items") or [item]:
                    places.append({
                        "title": place.get("title") or "",
                        "address": place.get("address") or "",
                        "rating": place.get("rating"),
                        "url": place.get("url") or place.get("domain") or "",
                    })
            return {"provider": self.name, "query": query, "places": places, "error": None}
        except Exception as exc:  # noqa: BLE001
            logger.warning("DataForSEO local_pack failed: %s",exc)
            return {"provider": self.name, "query": query, "places": [], "error": str(exc)[:200]}

    def directory_search(
        self,
        query: str,
        country: Optional[str] = None,
        num: int = 3,
    ) -> dict[str, Any]:
        # Directories stay on SerpAPI per capability map.
        return {
            "provider": self.name,
            "organic": [],
            "error": "provider_unavailable",
            "message": "Directory checks use SerpAPI",
        }


def _location_name(country: Optional[str]) -> str:
    mapping = {
        "AU": "Australia",
        "US": "United States",
        "GB": "United Kingdom",
        "UK": "United Kingdom",
        "NZ": "New Zealand",
        "CA": "Canada",
        "IN": "India",
    }
    if not country:
        return "United States"
    return mapping.get(country.upper(), country)
