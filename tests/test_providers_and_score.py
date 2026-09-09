"""Unit tests for SERP provider factory and SEO scoring."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.providers.serp.base import SerpCapability
from engine.providers.serp.factory import get_serp_provider
from engine.providers.serp.serpapi import SerpApiProvider
from engine.providers.serp.dataforseo import DataForSeoProvider
from engine.seo.score import compute_seo_score
from engine.keyword_gap_analysis import analyse_keyword_gaps


def test_factory_prefers_serpapi_for_directory_when_key_set(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    p = get_serp_provider(SerpCapability.DIRECTORY)
    assert isinstance(p, SerpApiProvider)
    assert p.is_configured()


def test_factory_keyword_ideas_uses_dataforseo_when_configured(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "user")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "pass")
    p = get_serp_provider(SerpCapability.KEYWORD_IDEAS)
    assert isinstance(p, DataForSeoProvider)
    assert p.is_configured()


def test_dataforseo_unavailable_without_creds(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    p = DataForSeoProvider(login="", password="")
    assert not p.is_configured()
    out = p.keyword_ideas("example.com")
    assert out.get("error") == "provider_unavailable"


def test_seo_score_deterministic():
    score = compute_seo_score(
        site_index={"indexed_count": 100},
        rankings={"summary": {"coverage_pct": 50}},
        backlinks={"referring_domains": 25, "backlinks": 100},
        local={"summary": {"share_pct": 40}},
        gbp={"listed": True},
        health={"summary": {
            "https_pct": 100,
            "title_pct": 90,
            "meta_pct": 80,
            "h1_pct": 70,
            "viewport_pct": 100,
            "schema_pct": 40,
            "robots_txt": True,
            "sitemap_xml": True,
        }},
        content_gaps={"gaps": []},
    )
    assert 0 <= score["overall"] <= 100
    assert set(score["pillars"]) == {"technical", "content", "authority", "experience", "local"}


def test_ai_keyword_gap_golden_shape():
    results = [
        {
            "prompt_id": 1,
            "prompt_text": "best crm",
            "category": "general",
            "engine": "openai",
            "brand_mentioned": False,
            "competitor_mentions": ["RivalCo"],
            "response_text": "RivalCo is great",
        },
        {
            "prompt_id": 1,
            "prompt_text": "best crm",
            "category": "general",
            "engine": "anthropic",
            "brand_mentioned": False,
            "competitor_mentions": ["RivalCo"],
            "response_text": "Try RivalCo",
        },
    ]
    out = analyse_keyword_gaps(results, brand="Acme", competitors=["RivalCo"])
    assert "keyword_gaps" in out
    assert out["keyword_gaps"][0]["prompt_id"] == 1


def test_serpapi_site_index_without_key(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    p = SerpApiProvider(api_key="")
    out = p.site_index("example.com")
    assert out["indexed_count"] == 0
    assert out.get("error")
