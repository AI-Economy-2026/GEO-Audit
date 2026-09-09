"""SERP provider abstraction: SerpAPI/SearchAPI + DataForSEO."""

from .base import SerpCapability, SerpProvider
from .factory import get_serp_provider, provider_status

__all__ = [
    "SerpCapability",
    "SerpProvider",
    "get_serp_provider",
    "provider_status",
]
