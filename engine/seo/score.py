"""SEO score: Technical, Content, Authority, Experience + Local pillars."""

from __future__ import annotations

from typing import Any


WEIGHTS = {
    "technical": 0.22,
    "content": 0.22,
    "authority": 0.22,
    "experience": 0.17,
    "local": 0.17,
}


def _clamp(score: float) -> float:
    return round(max(0.0, min(100.0, score)), 1)


def score_technical(site_index: dict, health: dict | None) -> float:
    indexed = float((site_index or {}).get("indexed_count") or 0)
    index_score = 40.0 if indexed <= 0 else min(70.0, 30.0 + (indexed ** 0.5))
    if not health or not health.get("summary"):
        return _clamp(index_score)
    s = health["summary"]
    extras = (
        (10.0 if s.get("robots_txt") else 0.0)
        + (10.0 if s.get("sitemap_xml") else 0.0)
        + (s.get("https_pct") or 0) * 0.1
    )
    return _clamp(index_score * 0.7 + extras)


def score_content(rankings: dict, content_gaps: dict | None) -> float:
    summary = (rankings or {}).get("summary") or {}
    coverage = float(summary.get("coverage_pct") or 0)
    gaps = (content_gaps or {}).get("gaps") or []
    # Fewer gaps vs volume of competitor keywords → higher score
    gap_penalty = min(40.0, len(gaps) * 0.8)
    return _clamp(coverage * 0.85 + (40.0 - gap_penalty) * 0.4)


def score_authority(backlinks: dict | None) -> float:
    if not backlinks or backlinks.get("error"):
        return 35.0  # neutral when provider unavailable
    rd = float(backlinks.get("referring_domains") or 0)
    bl = float(backlinks.get("backlinks") or 0)
    # Log-ish curve
    rd_score = min(70.0, (rd ** 0.5) * 8)
    bl_score = min(30.0, (bl ** 0.4) * 3)
    return _clamp(rd_score + bl_score)


def score_experience(health: dict | None) -> float:
    if not health or not health.get("summary"):
        return 40.0
    s = health["summary"]
    return _clamp(
        (s.get("title_pct") or 0) * 0.25
        + (s.get("meta_pct") or 0) * 0.2
        + (s.get("h1_pct") or 0) * 0.2
        + (s.get("viewport_pct") or 0) * 0.2
        + (s.get("schema_pct") or 0) * 0.15
    )


def score_local(local: dict | None, gbp: dict | None) -> float:
    share = float(((local or {}).get("summary") or {}).get("share_pct") or 0)
    gbp_bonus = 20.0 if (gbp or {}).get("listed") else 0.0
    return _clamp(share * 0.8 + gbp_bonus)


def compute_seo_score(
    *,
    site_index: dict,
    rankings: dict,
    backlinks: dict | None,
    local: dict | None,
    gbp: dict | None,
    health: dict | None,
    content_gaps: dict | None,
) -> dict[str, Any]:
    pillars = {
        "technical": score_technical(site_index, health),
        "content": score_content(rankings, content_gaps),
        "authority": score_authority(backlinks),
        "experience": score_experience(health),
        "local": score_local(local, gbp),
    }
    overall = _clamp(sum(pillars[k] * WEIGHTS[k] for k in WEIGHTS))
    return {
        "overall": overall,
        "pillars": pillars,
        "weights": WEIGHTS,
    }
