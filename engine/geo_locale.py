"""
Country / locale helpers for country-based audits.

Single source of truth mapping a country name to its Google `gl`/`hl`
codes (used by SerpAPI/searchapi) and to a prompt prefix (used to
localise the LLM engines). Everything is opt-in: when country is None
the helpers return empty/None and behaviour is unchanged.
"""
from __future__ import annotations
from typing import Optional

# Country name -> search locale. Keep keys in sync with the frontend dropdown.
COUNTRY_LOCALE: dict[str, dict[str, str]] = {
    "United Kingdom":       {"gl": "uk", "hl": "en", "location": "United Kingdom"},
    "United States":        {"gl": "us", "hl": "en", "location": "United States"},
    "Australia":            {"gl": "au", "hl": "en", "location": "Australia"},
    "India":                {"gl": "in", "hl": "en", "location": "India"},
    "Canada":               {"gl": "ca", "hl": "en", "location": "Canada"},
    "Ireland":              {"gl": "ie", "hl": "en", "location": "Ireland"},
    "New Zealand":          {"gl": "nz", "hl": "en", "location": "New Zealand"},
    "Singapore":            {"gl": "sg", "hl": "en", "location": "Singapore"},
    "United Arab Emirates": {"gl": "ae", "hl": "en", "location": "United Arab Emirates"},
    "Germany":              {"gl": "de", "hl": "de", "location": "Germany"},
    "France":               {"gl": "fr", "hl": "fr", "location": "France"},
    "Netherlands":          {"gl": "nl", "hl": "nl", "location": "Netherlands"},
    "Spain":                {"gl": "es", "hl": "es", "location": "Spain"},
}

# Engines that scrape live search results — they take the raw query, so the
# country is applied via search locale (gl/hl), NOT via a prompt prefix.
SCRAPER_ENGINES = {"google_ai_mode", "google_ai_overview", "bing_copilot"}


def locale_for(country: Optional[str]) -> Optional[dict[str, str]]:
    """Return {gl, hl, location} for a country, or None if unknown/unset."""
    if not country:
        return None
    return COUNTRY_LOCALE.get(country)


def location_prompt_prefix(country: Optional[str]) -> str:
    """A short instruction prepended to LLM prompts to localise answers.
    Empty string when no country is set (no behaviour change)."""
    if not country:
        return ""
    return (
        f"Answer as if the person asking is based in {country}. "
        f"Prioritise companies, providers and information most relevant to {country}.\n\n"
    )
