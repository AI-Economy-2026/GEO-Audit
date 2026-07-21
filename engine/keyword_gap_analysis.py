"""
Keyword Gap Analysis
=====================
Analyses audit results to identify where the brand is missing,
which competitors dominate, and where opportunities exist.

Ported from Agent Alice's alice_gap_analyser.py for use in the GEO worker.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass


def analyse_keyword_gaps(
    results: list[dict],
    brand: str,
    competitors: list[str],
) -> dict:
    """
    Produce a structured keyword gap analysis from audit result rows.

    Args:
        results: list of result dicts (from geo_audit_results table rows)
        brand: client brand name
        competitors: list of competitor names

    Returns dict with:
        keyword_gaps, strengths, low_competition,
        keyword_frequency, competitor_advantages
    """
    # Build per-prompt map
    prompt_map: dict[int, dict] = {}
    for r in results:
        pid = r["prompt_id"]
        if pid not in prompt_map:
            prompt_map[pid] = {
                "prompt_id": pid,
                "prompt_text": r["prompt_text"],
                "category": r["category"],
                "engines_tested": 0,
                "engines_mentioned": 0,
                "engines_missed": [],
                "engines_hit": [],
                "competitors_mentioned_in_gaps": [],
            }
        pm = prompt_map[pid]
        pm["engines_tested"] += 1

        is_error = r.get("response_text", "").startswith("[ERROR]")
        if is_error:
            continue

        if r.get("brand_mentioned"):
            pm["engines_mentioned"] += 1
            pm["engines_hit"].append(r["engine"])
        else:
            pm["engines_missed"].append(r["engine"])
            for comp in (r.get("competitor_mentions") or []):
                pm["competitors_mentioned_in_gaps"].append(comp)

    # --- Keyword Gaps: prompts where competitors mentioned but client isn't ---
    keyword_gaps = []
    for pm in sorted(prompt_map.values(), key=lambda p: p["engines_mentioned"]):
        if not pm["engines_missed"]:
            continue
        comp_counts = Counter(pm["competitors_mentioned_in_gaps"])
        gap_severity = "critical" if pm["engines_mentioned"] == 0 else \
                       "high" if pm["engines_mentioned"] < pm["engines_tested"] / 3 else \
                       "medium" if pm["engines_mentioned"] < pm["engines_tested"] / 2 else "low"
        keyword_gaps.append({
            "prompt_id": pm["prompt_id"],
            "prompt_text": pm["prompt_text"],
            "category": pm["category"],
            "engines_missed": pm["engines_missed"],
            "engines_hit": pm["engines_hit"],
            "engines_tested": pm["engines_tested"],
            "gap_severity": gap_severity,
            "competitors_present": [
                {"name": c, "count": n} for c, n in comp_counts.most_common(5)
            ],
        })

    # --- Strengths: prompts where client IS mentioned ---
    strengths = []
    for pm in sorted(prompt_map.values(), key=lambda p: -p["engines_mentioned"]):
        if pm["engines_mentioned"] > 0:
            strengths.append({
                "prompt_id": pm["prompt_id"],
                "prompt_text": pm["prompt_text"],
                "category": pm["category"],
                "engines_hit": pm["engines_hit"],
                "coverage_rate": round(
                    pm["engines_mentioned"] / pm["engines_tested"] * 100, 1
                ) if pm["engines_tested"] else 0,
            })

    # --- Low Competition: prompts where nobody is mentioned ---
    low_competition = []
    for pm in prompt_map.values():
        valid_results = [
            r for r in results
            if r["prompt_id"] == pm["prompt_id"]
            and not r.get("response_text", "").startswith("[ERROR]")
        ]
        brand_mentioned = any(r.get("brand_mentioned") for r in valid_results)
        any_competitor = any(r.get("competitor_mentions") for r in valid_results)
        if not brand_mentioned and not any_competitor:
            low_competition.append({
                "prompt_id": pm["prompt_id"],
                "prompt_text": pm["prompt_text"],
                "category": pm["category"],
                "opportunity": "No brands mentioned, an easy win with targeted content",
            })

    # --- Keyword Frequency: common terms in AI responses ---
    all_text = " ".join(
        r.get("response_text", "")
        for r in results
        if not r.get("response_text", "").startswith("[ERROR]")
        and not r.get("response_text", "").startswith("[NO RESPONSE]")
    ).lower()

    # Extract meaningful bigrams
    words = re.findall(r"\b[a-z]{3,}\b", all_text)
    stopwords = {
        "the", "and", "for", "are", "this", "that", "with", "from",
        "have", "has", "they", "their", "which", "will", "can", "may",
        "also", "been", "these", "those", "some", "other", "more",
        "about", "into", "such", "than", "them", "well", "not", "but",
        "your", "you", "our", "its", "was", "were", "been", "being",
    }
    filtered = [w for w in words if w not in stopwords]
    bigrams = [f"{filtered[i]} {filtered[i+1]}" for i in range(len(filtered) - 1)]
    keyword_frequency = dict(Counter(bigrams).most_common(20))

    # --- Competitor Advantages: per-competitor where they beat the client ---
    competitor_advantages = []
    comp_prompt_map: dict[str, list[str]] = defaultdict(list)

    for r in results:
        if r.get("response_text", "").startswith("[ERROR]"):
            continue
        if not r.get("brand_mentioned"):
            for comp in (r.get("competitor_mentions") or []):
                comp_prompt_map[comp].append(r["prompt_text"])

    for comp_name in competitors or list(comp_prompt_map.keys())[:5]:
        prompts = comp_prompt_map.get(comp_name, [])
        if prompts:
            competitor_advantages.append({
                "competitor": comp_name,
                "advantage_count": len(prompts),
                "prompts_where_they_beat_us": list(set(prompts))[:10],
            })
    competitor_advantages.sort(key=lambda c: c["advantage_count"], reverse=True)

    return {
        "keyword_gaps": keyword_gaps,
        "strengths": strengths,
        "low_competition": low_competition,
        "keyword_frequency": keyword_frequency,
        "competitor_advantages": competitor_advantages,
    }
