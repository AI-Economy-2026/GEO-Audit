"""Protocol and shared types for SERP / SEO data providers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable


class SerpCapability(str, Enum):
    ORGANIC = "organic"
    KEYWORD_IDEAS = "keyword_ideas"
    BACKLINKS = "backlinks"
    LOCAL_PACK = "local_pack"
    SITE_INDEX = "site_index"
    DIRECTORY = "directory"


@runtime_checkable
class SerpProvider(Protocol):
    """Capability surface used by GEO + SEO modules."""

    name: str

    def is_configured(self) -> bool: ...

    def site_index(self, domain: str, country: Optional[str] = None) -> dict[str, Any]: ...

    def organic_results(
        self,
        query: str,
        country: Optional[str] = None,
        num: int = 10,
    ) -> dict[str, Any]: ...

    def keyword_ideas(
        self,
        domain: str,
        country: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]: ...

    def backlinks_summary(
        self,
        domain: str,
        country: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def local_pack(
        self,
        query: str,
        country: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def directory_search(
        self,
        query: str,
        country: Optional[str] = None,
        num: int = 3,
    ) -> dict[str, Any]: ...
