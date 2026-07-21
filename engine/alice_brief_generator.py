"""
Alice Brief Generator
======================
Generates structured content recommendations ("Alice Brief") from
audit results, keyword gaps, directory checks, and SERP analysis.

The brief is designed as a structured JSON that Agent Alice can consume
to create blogs, FAQ pages, comparison articles, and directory listings.
"""

from __future__ import annotations

from engine.text_clean import strip_em_dashes

CONTENT_TYPES = [
    "blog_post",
    "faq_page",
    "case_study",
    "comparison_article",
    "directory_listing",
    "landing_page",
]


def _build_alice_context(results: list[dict], brand: str, competitors: list[str]) -> list[dict]:
    context = []
    
    # Group results by engine
    engines = {r["engine"] for r in results}
    for engine in engines:
        engine_rows = [r for r in results if r["engine"] == engine]
        
        # Calculate visibility for this engine
        mentioned = sum(1 for r in engine_rows if r["brand_mentioned"])
        engine_visibility = round(mentioned / len(engine_rows) * 100) if engine_rows else 0
        
        # Count sentiment
        sentiments = {"positive": 0, "neutral": 0, "negative": 0}
        for r in engine_rows:
            if r["brand_mentioned"]:
                sentiments[r.get("sentiment", "neutral").lower()] += 1
                
        # Top mentioned competitors in this engine
        comp_counts = {}
        for r in engine_rows:
            for comp in r.get("competitor_mentions", []):
                comp_counts[comp] = comp_counts.get(comp, 0) + 1
        top_comps = sorted(comp_counts.items(), key=lambda k: k[1], reverse=True)[:3]
        
        engine_data = {
            "engine": engine,
            "queries_run": len(engine_rows),
            "visibility_rate_percent": engine_visibility,
            "sentiment_breakdown": sentiments,
            "top_competitors_mentioned": top_comps,
            "failed_queries": sum(1 for r in engine_rows if r.get("scraper_status") in ("failed", "no_overview", "error"))
        }
        context.append(engine_data)
        
    return context

def generate_alice_brief(
    results: list[dict],
    keyword_gaps: dict,
    directory_results: list[dict],
    serp_data: dict,
    brand: str,
    competitors: list[str],
) -> dict:
    """
    Generate a structured Alice Brief with content recommendations.

    Returns:
        {
            content_recommendations: [...],
            directory_actions: [...],
            keyword_opportunities: [...],
            serp_vs_ai_gaps: [...],
            summary_stats: {...},
        }
    """
    content_recommendations = []
    rec_id = 1

    # --- 1. From keyword gaps: create content for missed prompts ---
    for gap in keyword_gaps.get("keyword_gaps", []):
        severity = gap.get("gap_severity", "medium")
        competitors_present = [c["name"] for c in gap.get("competitors_present", [])[:3]]
        n_missed = len(gap.get("engines_missed", []))
        n_tested = gap.get("engines_tested", 1)

        # Priority scoring
        priority_score = (n_missed * 10) + (len(competitors_present) * 5)
        if severity == "critical":
            priority_score += 20
        elif severity == "high":
            priority_score += 10

        # Determine content type based on the gap
        if n_missed == n_tested:
            # Invisible everywhere: need a landing page
            content_type = "landing_page"
            title = f"Why {brand} is the Best Choice for {gap['category']}"
            outline = [
                f"Introduction: Address the query '{gap['prompt_text'][:60]}'",
                f"Position {brand} as a top provider with specific credentials",
                "Include client testimonials and case studies",
                "Add FAQ schema targeting this exact query",
                "Include comparison table vs competitors" if competitors_present else "Include industry benchmarks",
            ]
        elif competitors_present:
            # Competitors present: comparison article
            content_type = "comparison_article"
            top_comp = competitors_present[0]
            title = f"{brand} vs {top_comp}: Which is Better for {gap['category']}?"
            outline = [
                f"Introduction: Compare {brand} and {top_comp}",
                "Feature-by-feature comparison table",
                f"Why {brand} stands out (unique selling points)",
                "Customer reviews and social proof",
                "Conclusion with clear recommendation",
            ]
        else:
            # General gap: blog post
            content_type = "blog_post"
            title = f"Complete Guide to {gap['category']} by {brand}"
            outline = [
                f"Address the query: '{gap['prompt_text'][:60]}'",
                f"Position {brand} as an authority in {gap['category']}",
                "Include data, statistics, and expert insights",
                "Add structured data (FAQ schema, HowTo)",
                "Link to relevant service pages on the website",
            ]

        content_recommendations.append({
            "id": rec_id,
            "type": content_type,
            "title": strip_em_dashes(title),
            "target_query": gap["prompt_text"],
            "target_category": gap["category"],
            "priority_score": priority_score,
            "severity": severity,
            "rationale": strip_em_dashes(
                f"Brand is missing from {n_missed}/{n_tested} engines for this query. "
                + (f"Competitors {', '.join(competitors_present)} are being cited instead." if competitors_present
                   else "No competitors mentioned either, an opportunity for first-mover advantage.")
            ),
            "target_engines": gap.get("engines_missed", []),
            "competitors_to_beat": competitors_present,
            "suggested_outline": [strip_em_dashes(o) for o in outline],
        })
        rec_id += 1

    # Sort by priority score
    content_recommendations.sort(key=lambda r: r["priority_score"], reverse=True)

    # --- 2. From low competition: easy-win content ---
    for opp in keyword_gaps.get("low_competition", []):
        content_recommendations.append({
            "id": rec_id,
            "type": "blog_post",
            "title": strip_em_dashes(f"{brand}'s Approach to {opp['category']}"),
            "target_query": opp["prompt_text"],
            "target_category": opp["category"],
            "priority_score": 30,  # Medium priority, easy win
            "severity": "opportunity",
            "rationale": "No brands mentioned for this query, a first-mover advantage.",
            "target_engines": [],
            "competitors_to_beat": [],
            "suggested_outline": [
                strip_em_dashes(f"Create authoritative content answering: '{opp['prompt_text'][:60]}'"),
                "Include industry data and expert opinions",
                "Add structured data for AI engine discoverability",
                "Publish on high-authority third-party sites as well",
            ],
        })
        rec_id += 1

    # --- 3. Directory actions ---
    directory_actions = []
    for d in directory_results:
        if d.get("error"):
            action = "check_manually"
            urgency = "low"
        elif d.get("listed"):
            action = "optimise"
            urgency = "low"
        else:
            action = "claim"
            urgency = "high"

        directory_actions.append({
            "directory": d["directory"],
            "listed": d.get("listed", False),
            "current_link": d.get("link"),
            "action": action,
            "urgency": urgency,
            "recommendation": strip_em_dashes(
                f"Optimise your existing {d['directory']} listing with updated info and keywords."
                if action == "optimise"
                else f"Claim your {d['directory']} listing to improve AI engine citations."
                if action == "claim"
                else f"Manually check {d['directory']}, the automated check failed."
            ),
        })

    # --- 4. SERP vs AI gaps ---
    serp_vs_ai_gaps = []
    for comp in serp_data.get("comparisons", []):
        if comp.get("gap_type") == "seo_strong_ai_weak":
            serp_vs_ai_gaps.append({
                "prompt_text": comp["prompt_text"],
                "organic_rank": comp.get("organic_rank"),
                "gap_type": "seo_strong_ai_weak",
                "recommendation": (
                    f"You rank #{comp.get('organic_rank', '?')} on Google but AI engines "
                    f"don't mention you. Add structured data, FAQ schema, and "
                    f"ensure content is AI-parseable."
                ),
                "priority": "high",
            })
        elif comp.get("gap_type") == "both_weak":
            serp_vs_ai_gaps.append({
                "prompt_text": comp["prompt_text"],
                "organic_rank": None,
                "gap_type": "both_weak",
                "recommendation": (
                    "Not ranking on Google or AI engines. Create foundational "
                    "content targeting this query with both SEO and GEO best practices."
                ),
                "priority": "critical",
            })

    # --- 5. Summary stats ---
    critical_count = sum(1 for r in content_recommendations if r.get("severity") == "critical")
    dirs_to_claim = sum(1 for d in directory_actions if d["action"] == "claim")

    summary_stats = {
        "total_recommendations": len(content_recommendations),
        "critical_count": critical_count,
        "content_pieces_needed": len(content_recommendations),
        "directories_to_claim": dirs_to_claim,
        "directories_to_optimise": sum(1 for d in directory_actions if d["action"] == "optimise"),
        "seo_strong_ai_weak_count": serp_data.get("summary", {}).get("seo_strong_ai_weak", 0),
        "both_weak_count": serp_data.get("summary", {}).get("both_weak", 0),
    }

    summarized_results = _build_alice_context(results, brand, competitors)

    return {
        "engine_visibility_data": summarized_results,
        "content_recommendations": content_recommendations[:20],  # Top 20
        "directory_actions": directory_actions,
        "keyword_opportunities": serp_vs_ai_gaps,
        "summary_stats": summary_stats,
    }
