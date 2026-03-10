#!/usr/bin/env python3
"""
GEO Dashboard Generator (Web Worker Edition)
==============================================
Identical analysis and rendering logic to the CLI version.

Added: render_dashboard_from_data() that accepts list-of-dicts and returns HTML string.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ENGINE_DISPLAY_NAMES = {
    "openai": "ChatGPT",
    "anthropic": "Claude",
    "google": "Gemini",
    "perplexity": "Perplexity",
    "copilot": "Copilot",
    "xai": "Grok",
    "deepseek": "DeepSeek",
    "meta_llama": "Llama",
    "google_ai_mode": "AI Mode",
    "google_ai_overview": "AI Overview",
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "grok": "Grok",
}

ENGINE_ICONS = {
    "ChatGPT": "G",
    "Claude": "C",
    "Perplexity": "P",
    "Gemini": "Ge",
    "Copilot": "Co",
    "Grok": "Gk",
    "DeepSeek": "DS",
    "Llama": "Ll",
    "AI Mode": "AM",
    "AI Overview": "AO",
}

CATEGORY_ORDER = [
    "Managed IT Services",
    "Systems Integrator",
    "Competitive Landscape",
]

ENGINE_ORDER = [
    "ChatGPT", "Claude", "Perplexity", "Gemini", "Grok",
    "DeepSeek", "Llama", "AI Mode", "AI Overview", "Copilot",
]


# ---------------------------------------------------------------------------
# Normalise engine name
# ---------------------------------------------------------------------------
def normalise_engine_name(engine: str) -> str:
    engine_lower = engine.lower().strip()
    if engine_lower in ENGINE_DISPLAY_NAMES:
        return ENGINE_DISPLAY_NAMES[engine_lower]
    for key, display in ENGINE_DISPLAY_NAMES.items():
        if key in engine_lower or engine_lower in key:
            return display
    return engine


# ---------------------------------------------------------------------------
# Data preparation from list-of-dicts
# ---------------------------------------------------------------------------
def _prepare_rows(rows: list[dict]) -> list[dict]:
    """Normalise raw row dicts (from Supabase or CSV) to the format AuditAnalysis expects."""
    prepared = []
    for row in rows:
        r = dict(row)  # shallow copy

        # Normalise brand_mentioned
        bm = r.get("brand_mentioned", False)
        if isinstance(bm, str):
            r["brand_mentioned"] = bm.lower() in ("true", "1", "yes")

        # Normalise url_cited
        uc = r.get("url_cited", False)
        if isinstance(uc, str):
            r["url_cited"] = uc.lower() in ("true", "1", "yes")

        # Parse position_rank
        pr = r.get("position_rank", None)
        if isinstance(pr, str):
            r["position_rank"] = int(pr) if pr and pr.isdigit() else None

        # Parse competitor_mentions
        cm = r.get("competitor_mentions", [])
        if isinstance(cm, str):
            r["competitor_mentions"] = [c.strip() for c in cm.split(";") if c.strip()] if cm else []

        # Engine display name
        engine_raw = r.get("engine", "").strip()
        r["engine_display"] = normalise_engine_name(engine_raw)

        prepared.append(r)

    return prepared


# ---------------------------------------------------------------------------
# AuditAnalysis (identical to CLI version)
# ---------------------------------------------------------------------------
class AuditAnalysis:
    def __init__(self, rows: list[dict], client_name: str, client_url: str):
        self.rows = rows
        self.client_name = client_name
        self.client_url = client_url
        self.valid_rows = [
            r for r in rows
            if not r.get("response_text", "").startswith("[ERROR]")
        ]
        self.prompt_ids = sorted(set(int(r["prompt_id"]) for r in self.valid_rows))
        self.categories = sorted(
            set(r["category"] for r in self.valid_rows),
            key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 999,
        )
        self.engines = sorted(
            set(r["engine_display"] for r in self.valid_rows),
            key=lambda e: ENGINE_ORDER.index(e) if e in ENGINE_ORDER else 999,
        )
        self._calc_overall()
        self._calc_per_engine()
        self._calc_per_category()
        self._calc_competitors()
        self._calc_per_prompt()
        self._calc_category_rankings()
        self._generate_findings()
        self._generate_recommendations()

    def _calc_overall(self):
        total = len(self.valid_rows)
        mentioned = sum(1 for r in self.valid_rows if r["brand_mentioned"])
        self.total_prompts = len(self.prompt_ids)
        self.total_queries = total
        self.total_mentioned = mentioned
        self.visibility_rate = round(mentioned / total * 100) if total else 0
        ranks = [r["position_rank"] for r in self.valid_rows if r["position_rank"] is not None]
        self.best_rank = min(ranks) if ranks else None
        self.engine_count = len(self.engines)
        self.category_count = len(self.categories)

    def _calc_per_engine(self):
        self.engine_data = []
        for engine in self.engines:
            engine_rows = [r for r in self.valid_rows if r["engine_display"] == engine]
            total = len(engine_rows)
            mentioned = sum(1 for r in engine_rows if r["brand_mentioned"])
            missed = total - mentioned
            rate = round(mentioned / total * 100) if total else 0
            gap = 100 - rate
            self.engine_data.append({
                "name": engine, "icon": ENGINE_ICONS.get(engine, engine[:2]),
                "rate": rate, "missed": missed, "gap": gap,
                "total": total, "mentioned": mentioned,
            })

    def _calc_per_category(self):
        self.category_data = []
        for cat in self.categories:
            cat_rows = [r for r in self.valid_rows if r["category"] == cat]
            total = len(cat_rows)
            mentioned = sum(1 for r in cat_rows if r["brand_mentioned"])
            vis_rate = round(mentioned / total * 100) if total else 0
            ranks = [r["position_rank"] for r in cat_rows if r["position_rank"] is not None]
            avg_rank = round(mean(ranks), 1) if ranks else None
            total_comp = sum(len(r["competitor_mentions"]) for r in cat_rows)
            sov = round(mentioned / (mentioned + total_comp) * 100) if (mentioned + total_comp) > 0 else 0
            vis_class = "vis-high" if vis_rate >= 70 else "vis-med" if vis_rate >= 40 else "vis-low"
            rank_class = "rank-high" if avg_rank and avg_rank <= 2 else "rank-med" if avg_rank and avg_rank <= 4 else "rank-low"
            self.category_data.append({
                "name": cat, "visibility": vis_rate, "vis_class": vis_class,
                "avg_rank": avg_rank, "rank_display": str(round(avg_rank)) if avg_rank else "-",
                "rank_class": rank_class, "sov": sov, "total": total, "mentioned": mentioned,
            })

    def _calc_competitors(self):
        comp_counts: Counter = Counter()
        for r in self.valid_rows:
            for comp in r["competitor_mentions"]:
                comp_counts[comp] += 1
        self.top_competitors = comp_counts.most_common(10)

    def _calc_category_rankings(self):
        self.category_rankings = []
        for cat in self.categories:
            cat_rows = [r for r in self.valid_rows if r["category"] == cat]
            client_mentions = sum(1 for r in cat_rows if r["brand_mentioned"])
            comp_counts: Counter = Counter()
            for r in cat_rows:
                for comp in r["competitor_mentions"]:
                    comp_counts[comp] += 1
            all_brands = [{"brand": self.client_name, "mentions": client_mentions, "isClient": True}]
            for comp_name, comp_count in comp_counts.most_common(10):
                all_brands.append({"brand": comp_name, "mentions": comp_count, "isClient": False})
            all_brands.sort(key=lambda b: b["mentions"], reverse=True)
            total_mentions = sum(b["mentions"] for b in all_brands)
            ranked = []
            for i, b in enumerate(all_brands[:8], 1):
                sov = round(b["mentions"] / total_mentions * 100) if total_mentions > 0 else 0
                ranked.append({"rank": i, "brand": b["brand"], "mentions": b["mentions"], "sov": sov, "isClient": b["isClient"]})
            self.category_rankings.append({"category": cat, "brands": ranked})

    def _calc_per_prompt(self):
        prompt_map: dict[int, dict] = {}
        for r in self.valid_rows:
            pid = int(r["prompt_id"])
            if pid not in prompt_map:
                prompt_map[pid] = {"id": pid, "prompt": r["prompt_text"], "category": r["category"], "engines": {}}
            engine = r["engine_display"]
            excerpt = self._make_excerpt(r.get("response_text", ""), 500)
            prompt_map[pid]["engines"][engine] = {"mentioned": r["brand_mentioned"], "excerpt": excerpt}
        self.prompt_data = [prompt_map[pid] for pid in sorted(prompt_map.keys())]

    def _make_excerpt(self, text: str, max_len: int = 200) -> str:
        if not text:
            return "No response available."
        text = text.replace('"', "'").replace("\n", " ").strip()
        if len(text) > max_len:
            cut = text[:max_len].rfind(". ")
            if cut > max_len * 0.5:
                return text[:cut + 1]
            return text[:max_len] + "..."
        return text

    def _generate_findings(self):
        findings = []
        best_cat = max(self.category_data, key=lambda c: c["visibility"])
        worst_cat = min(self.category_data, key=lambda c: c["visibility"])
        findings.append(
            f"{self.client_name} achieves a {self.visibility_rate}% overall "
            f"AI visibility rate, with strongest performance in "
            f"{best_cat['name']} ({best_cat['visibility']}%) and lowest in "
            f"{worst_cat['name']} ({worst_cat['visibility']}%)."
        )
        best_engine = max(self.engine_data, key=lambda e: e["rate"])
        low_engines = [e for e in self.engine_data if e["rate"] < self.visibility_rate]
        if low_engines:
            low_str = " and ".join(f"{e['name']} ({e['rate']}%)" for e in low_engines)
            findings.append(
                f"{best_engine['name']} is the strongest-performing engine "
                f"at {best_engine['rate']}% mention rate, while {low_str} "
                f"represent the largest gaps and immediate improvement opportunities."
            )
        else:
            worst_engine = min(self.engine_data, key=lambda e: e["rate"])
            findings.append(
                f"{best_engine['name']} leads at {best_engine['rate']}% mention rate. "
                f"{worst_engine['name']} at {worst_engine['rate']}% represents the primary improvement opportunity."
            )
        if self.best_rank is not None and self.best_rank <= 2:
            top_rank_rows = [r for r in self.valid_rows if r["position_rank"] is not None and r["position_rank"] <= 2]
            findings.append(
                f"{self.client_name} achieves a top-2 ranking position in "
                f"{len(top_rank_rows)} queries across the audit. "
                f"{best_cat['name']} queries yield the highest visibility "
                f"({best_cat['visibility']}%), indicating strong brand association in this segment."
            )
        else:
            findings.append(
                f"The {best_cat['name']} category shows strong brand recognition with "
                f"{best_cat['visibility']}% visibility. Expanding content in the "
                f"{worst_cat['name']} category ({worst_cat['visibility']}%) presents the largest growth opportunity."
            )
        self.findings = findings

    def _generate_recommendations(self):
        best_engine = max(self.engine_data, key=lambda e: e["rate"])
        best_cat = max(self.category_data, key=lambda c: c["visibility"])
        worst_cat = min(self.category_data, key=lambda c: c["visibility"])
        low_engines = sorted([e for e in self.engine_data if e["rate"] < self.visibility_rate], key=lambda e: e["rate"])
        low_engine_missed = sum(e["missed"] for e in low_engines)

        priorities = []
        if low_engines:
            engine_names = " and ".join(e["name"] for e in low_engines[:2])
            priorities.append(f"Address {engine_names} visibility gaps - these engines account for {low_engine_missed} missed opportunities. Create structured, schema-rich content targeting these platforms.")
        else:
            priorities.append("Maintain current visibility across all engines while focusing on improving ranking positions. Target top-3 placement in all queries.")
        priorities.append(f"Strengthen '{worst_cat['name']}' positioning with dedicated landing pages, case studies, and thought leadership content that AI engines can reference.")
        priorities.append("Build authoritative third-party citations on industry directories, comparison sites, and analyst reports to improve AI training data signals.")

        sector = []
        sector.append(f"Develop {worst_cat['name'].lower()} content - currently at {worst_cat['visibility']}% visibility. Publish case studies and comparison content targeting this segment.")
        if self.top_competitors:
            top_comps = ", ".join(c[0] for c in self.top_competitors[:3])
            sector.append(f"Create comparison content positioning {self.client_name} against {top_comps} to capture 'alternatives' and competitive queries.")
        else:
            sector.append(f"Create comparison content that positions {self.client_name} against key competitors to capture competitive queries.")
        sector.append("Invest in educational content to own informational queries and build topical authority across all service categories.")

        leverage = []
        leverage.append(f"Amplify the {best_cat['name']} advantage - {best_cat['visibility']}% visibility. Expand content library and PR efforts in this high-performing segment.")
        high_vis = [p for p in self.prompt_data if sum(1 for e in p["engines"].values() if e["mentioned"]) == len(p["engines"])]
        if high_vis:
            leverage.append(f"{self.client_name} appears in 100% of engines for {len(high_vis)} queries. Analyse these high-performing prompts and replicate the content patterns across weaker areas.")
        else:
            leverage.append(f"Identify queries where {self.client_name} appears in the most engines and analyse what content patterns drive visibility. Replicate these across weaker areas.")
        leverage.append(f"{best_engine['name']} at {best_engine['rate']}% shows the strongest engine affinity. Analyse {best_engine['name']}'s content preferences and replicate successful patterns across other engines.")

        self.rec_priorities = priorities
        self.rec_sector = sector
        self.rec_leverage = leverage

    def generate_executive_summary(self) -> str:
        cat_names = ", ".join(self.categories[:-1])
        if len(self.categories) > 1:
            cat_names += f", and {self.categories[-1]}"
        elif self.categories:
            cat_names = self.categories[0]
        engine_names = ", ".join(self.engines[:-1])
        if len(self.engines) > 1:
            engine_names += f", and {self.engines[-1]}"
        elif self.engines:
            engine_names = self.engines[0]
        return (
            f"This comprehensive audit analyses {self.client_name}'s "
            f"visibility across {self.total_prompts} search prompts spanning "
            f"{len(self.categories)} categories: {cat_names}. Testing was "
            f"conducted across {len(self.engines)} leading AI engines "
            f"\\u2014 {engine_names} \\u2014 to measure how frequently "
            f"{self.client_name} is surfaced in generative AI responses to "
            f"queries that real buyers and decision-makers would use."
        )


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------
def _build_competitor_data(analysis: AuditAnalysis) -> list[dict]:
    all_brands: list[dict] = []
    ranks = [r["position_rank"] for r in analysis.valid_rows if r["position_rank"] is not None and r["brand_mentioned"]]
    if ranks:
        min_rank, max_rank = min(ranks), max(ranks)
        position_str = f"{min_rank}-{max_rank}" if min_rank != max_rank else str(min_rank)
    else:
        position_str = "-"
    client_citations = sum(1 for r in analysis.valid_rows if r.get("url_cited"))
    all_brands.append({"brand": analysis.client_name, "mentions": analysis.total_mentioned, "citations": client_citations, "position": position_str, "isClient": True})
    for comp_name, comp_count in analysis.top_competitors:
        all_brands.append({"brand": comp_name, "mentions": comp_count, "citations": max(0, comp_count - (comp_count // 3)), "position": "-", "isClient": False})
    all_brands.sort(key=lambda b: b["mentions"], reverse=True)
    total_mentions = sum(b["mentions"] for b in all_brands)
    result = []
    for i, b in enumerate(all_brands[:10], 1):
        sov = round(b["mentions"] / total_mentions * 100) if total_mentions > 0 else 0
        result.append({"rank": i, "brand": b["brand"], "mentions": b["mentions"], "sov": sov, "position": b["position"], "citations": b["citations"], "isClient": b["isClient"]})
    return result


def _build_replacements(analysis: AuditAnalysis) -> dict[str, str]:
    today = datetime.now().strftime("%-d %B %Y")
    r: dict[str, str] = {}
    r["CLIENT_NAME"] = analysis.client_name
    r["CLIENT_URL"] = analysis.client_url
    r["REPORT_DATE"] = today
    r["EXECUTIVE_SUMMARY"] = analysis.generate_executive_summary()
    for i, finding in enumerate(analysis.findings[:3], 1):
        r[f"FINDING_{i}"] = finding
    for i in range(len(analysis.findings) + 1, 4):
        r[f"FINDING_{i}"] = "Additional analysis required."
    r["TOTAL_PROMPTS"] = str(analysis.total_prompts)
    r["TOTAL_QUERIES"] = str(analysis.total_queries)
    r["TOTAL_MENTIONED"] = str(analysis.total_mentioned)
    r["VISIBILITY_RATE"] = str(analysis.visibility_rate)
    r["ENGINE_COUNT"] = str(analysis.engine_count)
    r["BEST_RANK"] = str(analysis.best_rank) if analysis.best_rank else "-"
    r["CATEGORIES"] = f"{analysis.category_count} categories"
    r["CATEGORY_COUNT"] = str(analysis.category_count)
    r["ENGINE_NAMES_SHORT"] = ", ".join(analysis.engines)
    best_cat = max(analysis.category_data, key=lambda c: c["visibility"])
    worst_cat = min(analysis.category_data, key=lambda c: c["visibility"])
    r["BEST_CATEGORY"] = f"{best_cat['name']} ({best_cat['visibility']}%)"
    r["WORST_CATEGORY"] = f"{worst_cat['name']} ({worst_cat['visibility']}%)"
    for i, cat in enumerate(analysis.category_data[:3], 1):
        r[f"CATEGORY_{i}_NAME"] = cat["name"]
        r[f"CATEGORY_{i}_VISIBILITY"] = f"{cat['visibility']}%"
        r[f"CATEGORY_{i}_VIS_CLASS"] = cat["vis_class"]
        r[f"CATEGORY_{i}_RANK"] = cat["rank_display"]
        r[f"CATEGORY_{i}_RANK_CLASS"] = cat["rank_class"]
        r[f"CATEGORY_{i}_SOV"] = str(cat["sov"])
    for i in range(len(analysis.category_data) + 1, 4):
        r[f"CATEGORY_{i}_NAME"] = "-"
        r[f"CATEGORY_{i}_VISIBILITY"] = "0%"
        r[f"CATEGORY_{i}_VIS_CLASS"] = "vis-low"
        r[f"CATEGORY_{i}_RANK"] = "-"
        r[f"CATEGORY_{i}_RANK_CLASS"] = "rank-low"
        r[f"CATEGORY_{i}_SOV"] = "0"
    for i, rec in enumerate(analysis.rec_priorities[:3], 1):
        r[f"REC_PRIORITY_{i}"] = rec
    for i in range(len(analysis.rec_priorities) + 1, 4):
        r[f"REC_PRIORITY_{i}"] = "Further analysis needed."
    for i, rec in enumerate(analysis.rec_sector[:3], 1):
        r[f"REC_SECTOR_{i}"] = rec
    for i in range(len(analysis.rec_sector) + 1, 4):
        r[f"REC_SECTOR_{i}"] = "Further analysis needed."
    for i, rec in enumerate(analysis.rec_leverage[:3], 1):
        r[f"REC_LEVERAGE_{i}"] = rec
    for i in range(len(analysis.rec_leverage) + 1, 4):
        r[f"REC_LEVERAGE_{i}"] = "Further analysis needed."
    return r


def render_dashboard_html(
    analysis: AuditAnalysis,
    template_path: str,
) -> str:
    """Read template and return rendered HTML string."""
    with open(template_path, encoding="utf-8") as fh:
        html = fh.read()

    replacements = _build_replacements(analysis)
    for key, value in replacements.items():
        html = html.replace("{{" + key + "}}", str(value))

    engine_json = json.dumps([
        {"name": e["name"], "icon": e["icon"], "rate": e["rate"],
         "missed": e["missed"], "gap": e["gap"], "total": e["total"],
         "mentioned": e["mentioned"]}
        for e in analysis.engine_data
    ], indent=2)
    prompt_json = json.dumps(analysis.prompt_data, indent=2)
    competitor_json = json.dumps(_build_competitor_data(analysis), indent=2)
    cat_rankings_json = json.dumps(analysis.category_rankings, indent=2)
    cat_perf_json = json.dumps([
        {"name": c["name"], "visibility": c["visibility"], "sov": c["sov"]}
        for c in analysis.category_data
    ], indent=2)

    html = html.replace("{{ENGINE_DATA}}", engine_json)
    html = html.replace("{{PROMPT_DATA}}", prompt_json)
    html = html.replace("{{COMPETITOR_DATA}}", competitor_json)
    html = html.replace("{{CATEGORY_RANKINGS}}", cat_rankings_json)
    html = html.replace("{{CATEGORY_PERF}}", cat_perf_json)

    return html


# ---------------------------------------------------------------------------
# Public API for the worker
# ---------------------------------------------------------------------------
def render_dashboard_from_data(
    rows: list[dict],
    client_name: str,
    client_url: str,
    template_path: str,
) -> str:
    """
    Generate a complete HTML dashboard from in-memory row data.

    Args:
        rows: List of dicts matching the audit result schema
        client_name: Brand name
        client_url: Brand URL
        template_path: Path to geo-dashboard-template.html

    Returns:
        Complete HTML string of the dashboard
    """
    prepared = _prepare_rows(rows)
    analysis = AuditAnalysis(prepared, client_name, client_url)
    return render_dashboard_html(analysis, template_path)
