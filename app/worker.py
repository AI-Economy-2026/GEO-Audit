"""
Background audit worker.

Receives an audit_id, loads params from Supabase, runs the audit engine,
writes results and progress back to Supabase, generates the dashboard HTML,
uploads it to Supabase Storage, then runs analysis modules (keyword gaps,
directory checks, SERP analysis, Alice brief).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root (parent of app/) is on sys.path so that
# sibling packages like `engine` can be imported.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from .supabase_client import get_supabase, execute_with_retry
from engine.geo_audit_engine import (
    AuditResult,
    ENGINE_DISPLAY_NAMES,
    Prompt,
    generate_summary_dict,
    run_audit_async,
)
from engine.prompt_classifier import classify_prompt_type, classify_intent_type
from engine.generate_dashboard import render_dashboard_from_data
from engine.keyword_gap_analysis import analyse_keyword_gaps
from engine.directory_check import check_directories
from engine.serp_analysis import check_site_index, check_organic_rankings, compare_ai_vs_seo
from engine.alice_brief_generator import generate_alice_brief

logger = logging.getLogger(__name__)

# Path to the bundled template
TEMPLATE_PATH = str(Path(__file__).resolve().parent.parent / "engine" / "geo-dashboard-template.html")


def run_audit_task(audit_id: str) -> None:
    """
    Execute a full GEO audit as a background task.

    1. Load audit params + prompts from Supabase
    2. Mark as running
    3. Query each engine for each prompt (parallel, with progress updates)
    4. Run analysis modules (keyword gaps, directory check, SERP, Alice brief)
    5. Generate dashboard HTML
    6. Upload to Supabase Storage
    7. Mark as completed with summary stats
    """
    sb = get_supabase()
    start_time = time.time()

    try:
        # 1. Load audit params
        audit = (
            sb.table("geo_audits")
            .select("*")
            .eq("id", audit_id)
            .single()
            .execute()
        )
        params = audit.data

        # Check if cancelled before starting
        if params["status"] == "cancelled":
            logger.info(f"Audit {audit_id} was cancelled before starting.")
            return

        # Load prompts
        prompts_resp = (
            sb.table("geo_audit_prompts")
            .select("*")
            .eq("audit_id", audit_id)
            .order("prompt_id")
            .execute()
        )
        prompts = [
            Prompt(
                prompt_id=p["prompt_id"],
                category=p["category"],
                prompt_text=p["prompt_text"],
                prompt_type=classify_prompt_type(p["prompt_text"]),
                intent_type=classify_intent_type(p["prompt_text"]),
            )
            for p in prompts_resp.data
        ]

        if not prompts:
            _mark_failed(sb, audit_id, "No prompts found for this audit.")
            return

        engines = params["engines"]
        total = len(prompts) * len(engines)

        # 2. Mark as running
        sb.table("geo_audits").update({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "progress_current": 0,
            "progress_total": total,
            "progress_message": "Starting audit...",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()

        # 3. Run audit with progress callback (parallel via asyncio)
        all_result_rows: list[dict] = []

        def on_progress(completed: int, total_count: int, result: AuditResult) -> None:
            # Always fetch a fresh client — get_supabase() refreshes the
            # cached client every 45s, so this guards against stale HTTP/2
            # connections during long audits.
            sb_inner = get_supabase()

            # Check for cancellation periodically (every 10 queries)
            if completed % 10 == 0:
                check = execute_with_retry(
                    lambda: sb_inner.table("geo_audits").select("status").eq("id", audit_id).single().execute(),
                    op="cancellation check",
                )
                if check.data["status"] == "cancelled":
                    raise InterruptedError("Audit was cancelled.")

            engine_display = ENGINE_DISPLAY_NAMES.get(result.engine, result.engine)

            # Insert individual result row
            matched_prompt = next((p for p in prompts if p.prompt_id == result.prompt_id), None)
            row_data = {
                "audit_id": audit_id,
                "prompt_id": result.prompt_id,
                "category": result.category,
                "prompt_text": result.prompt_text,
                "prompt_type": matched_prompt.prompt_type if matched_prompt else classify_prompt_type(result.prompt_text),
                "intent_type": matched_prompt.intent_type if matched_prompt else classify_intent_type(result.prompt_text),
                "engine": result.engine,
                "engine_display": engine_display,
                "brand_mentioned": result.brand_mentioned,
                "position_rank": result.position_rank,
                "url_cited": result.url_cited,
                "competitor_mentions": result.competitor_mentions,
                "sentiment": result.sentiment,
                "response_text": result.response_text[:10000],  # cap at 10k chars
                # Persist every URL parsed from the LLM response so the
                # dashboard can build a "top-cited domains" view.
                "citations": (result.citation_data or {}).get("all_citations", []) or [],
            }
            execute_with_retry(
                lambda: get_supabase().table("geo_audit_results").insert(row_data).execute(),
                op=f"insert result prompt={result.prompt_id} engine={result.engine}",
            )

            # Also store for dashboard generation
            all_result_rows.append(row_data)

            # Update progress on audit row (triggers Supabase Realtime)
            mention_str = "mentioned" if result.brand_mentioned else "not mentioned"
            execute_with_retry(
                lambda: get_supabase().table("geo_audits").update({
                    "progress_current": completed,
                    "progress_message": (
                        f"[{completed}/{total_count}] {engine_display} — "
                        f"Prompt #{result.prompt_id}: {mention_str}"
                    ),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", audit_id).execute(),
                op="progress update",
            )

        # Run async audit (engine-level parallelism)
        results = asyncio.run(run_audit_async(
            prompts=prompts,
            brand=params["brand_name"],
            url=params["brand_url"],
            competitors=params["competitors"],
            engines=engines,
            progress_callback=on_progress,
        ))

        # Update progress for analysis phase
        sb.table("geo_audits").update({
            "progress_message": "Running analysis modules...",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()

        # 4. Run analysis modules
        # 4a. Generate base summary
        summary = generate_summary_dict(results, params["brand_name"], params.get("brand_url", ""))

        # 4b. Keyword gap analysis
        logger.info(f"Audit {audit_id}: Running keyword gap analysis...")
        keyword_gaps = analyse_keyword_gaps(
            results=all_result_rows,
            brand=params["brand_name"],
            competitors=params["competitors"],
        )
        summary["keyword_gap_analysis"] = keyword_gaps

        # 4c. Directory check
        logger.info(f"Audit {audit_id}: Running directory checks...")
        sb.table("geo_audits").update({
            "progress_message": "Checking business directories...",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()
        directory_results = check_directories(params["brand_name"])
        summary["directory_citations"] = directory_results

        # 4d. SERP analysis
        logger.info(f"Audit {audit_id}: Running SERP analysis...")
        sb.table("geo_audits").update({
            "progress_message": "Analysing organic search rankings...",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()

        site_index = check_site_index(params["brand_url"])

        prompt_dicts = [{"prompt_id": p.prompt_id, "prompt_text": p.prompt_text} for p in prompts]
        organic_rankings = check_organic_rankings(prompt_dicts, params["brand_url"])

        serp_comparison = compare_ai_vs_seo(all_result_rows, organic_rankings)
        summary["serp_analysis"] = {
            "site_indexed": site_index,
            "organic_rankings": organic_rankings,
            "comparisons": serp_comparison["comparisons"],
            "summary": serp_comparison["summary"],
        }

        # 4e. Alice brief
        logger.info(f"Audit {audit_id}: Generating content recommendations...")
        sb.table("geo_audits").update({
            "progress_message": "Generating content recommendations...",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()

        alice_brief = generate_alice_brief(
            results=all_result_rows,
            keyword_gaps=keyword_gaps,
            directory_results=directory_results,
            serp_data=serp_comparison,
            brand=params["brand_name"],
            competitors=params["competitors"],
        )
        summary["alice_brief"] = alice_brief
        print("ALICE BRIEF", alice_brief)
        # Store Alice brief in dedicated table (for Agent Alice to query)
        try:
            sb.table("geo_alice_briefs").insert({
                "audit_id": audit_id,
                "client_name": params["brand_name"],
                "brief_json": alice_brief,
                "status": "pending",
            }).execute()
        except Exception as brief_exc:
            logger.warning(f"Failed to insert Alice brief (table may not exist): {brief_exc}")

        # 5. Generate dashboard HTML
        dashboard_html = render_dashboard_from_data(
            rows=all_result_rows,
            client_name=params["brand_name"],
            client_url=params["brand_url"],
            template_path=TEMPLATE_PATH,
            keywords=params.get("keywords", []),
        )
        print("Dashboard HTML", dashboard_html) 

        # 6. Upload to Supabase Storage (upsert to handle re-runs)
        filename = f"{audit_id}/dashboard.html"
        sb.storage.from_("geo-dashboards").upload(
            filename,
            dashboard_html.encode("utf-8"),
            file_options={"content-type": "text/html", "upsert": "true"},
        )
        dashboard_url = sb.storage.from_("geo-dashboards").get_public_url(filename)

        # 7. Mark complete with full summary
        elapsed = int(time.time() - start_time)

        sb.table("geo_audits").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": elapsed,
            "dashboard_url": dashboard_url,
            "summary_json": summary,
            "visibility_rate": summary["overall_visibility"]["visibility_rate_percent"],
            "total_queries": summary["audit_metadata"]["total_queries"],
            "total_mentioned": summary["overall_visibility"]["brand_mentioned_count"],
            "progress_current": total,
            "progress_message": "Audit complete!",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()

        logger.info(
            f"Audit {audit_id} completed in {elapsed}s. "
            f"Visibility: {summary['overall_visibility']['visibility_rate_percent']}%"
        )

    except InterruptedError:
        logger.info(f"Audit {audit_id} was cancelled during execution.")
        sb.table("geo_audits").update({
            "status": "cancelled",
            "progress_message": "Audit cancelled by user.",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()

    except Exception as exc:
        logger.exception(f"Audit {audit_id} failed: {exc}")
        _mark_failed(sb, audit_id, str(exc))


def run_audit_extension(audit_id: str, prompt_ids: list[int]) -> None:
    """
    Run additional prompts for an existing completed audit.

    1. Load only the specified prompt_ids
    2. Query engines for just those prompts
    3. Re-read ALL results (old + new) and regenerate full summary
    4. On failure: revert to completed (original data is intact)
    """
    sb = get_supabase()
    start_time = time.time()

    try:
        # Load audit params
        audit = (
            sb.table("geo_audits")
            .select("*")
            .eq("id", audit_id)
            .single()
            .execute()
        )
        params = audit.data

        # Load only the new prompts
        prompts_resp = (
            sb.table("geo_audit_prompts")
            .select("*")
            .eq("audit_id", audit_id)
            .in_("prompt_id", prompt_ids)
            .order("prompt_id")
            .execute()
        )
        new_prompts = [
            Prompt(
                prompt_id=p["prompt_id"],
                category=p["category"],
                prompt_text=p["prompt_text"],
                prompt_type=classify_prompt_type(p["prompt_text"]),
                intent_type=classify_intent_type(p["prompt_text"]),
            )
            for p in prompts_resp.data
        ]

        if not new_prompts:
            logger.warning(f"Extension {audit_id}: No prompts found for IDs {prompt_ids}")
            sb.table("geo_audits").update({
                "status": "completed",
                "progress_message": "No new prompts to run.",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", audit_id).execute()
            return

        engines = params["engines"]
        total = len(new_prompts) * len(engines)
        new_result_rows: list[dict] = []

        def on_progress(completed: int, total_count: int, result: AuditResult) -> None:
            engine_display = ENGINE_DISPLAY_NAMES.get(result.engine, result.engine)

            matched_prompt = next((p for p in new_prompts if p.prompt_id == result.prompt_id), None)
            row_data = {
                "audit_id": audit_id,
                "prompt_id": result.prompt_id,
                "category": result.category,
                "prompt_text": result.prompt_text,
                "prompt_type": matched_prompt.prompt_type if matched_prompt else classify_prompt_type(result.prompt_text),
                "intent_type": matched_prompt.intent_type if matched_prompt else classify_intent_type(result.prompt_text),
                "engine": result.engine,
                "engine_display": engine_display,
                "brand_mentioned": result.brand_mentioned,
                "position_rank": result.position_rank,
                "url_cited": result.url_cited,
                "competitor_mentions": result.competitor_mentions,
                "sentiment": result.sentiment,
                "response_text": result.response_text[:10000],
            }
            sb.table("geo_audit_results").insert(row_data).execute()
            new_result_rows.append(row_data)

            mention_str = "mentioned" if result.brand_mentioned else "not mentioned"
            sb.table("geo_audits").update({
                "progress_current": completed,
                "progress_message": (
                    f"[{completed}/{total_count}] {engine_display} — "
                    f"Prompt #{result.prompt_id}: {mention_str}"
                ),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", audit_id).execute()

        # Run only new prompts
        logger.info(f"Extension {audit_id}: Running {len(new_prompts)} new prompts across {len(engines)} engines")
        asyncio.run(run_audit_async(
            prompts=new_prompts,
            brand=params["brand_name"],
            url=params["brand_url"],
            competitors=params["competitors"],
            engines=engines,
            progress_callback=on_progress,
        ))

        # Now regenerate full summary from ALL results
        sb.table("geo_audits").update({
            "progress_message": "Recalculating results...",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()

        all_results_resp = (
            sb.table("geo_audit_results")
            .select("*")
            .eq("audit_id", audit_id)
            .execute()
        )
        all_result_rows = all_results_resp.data

        # Load all prompts to map prompt_type
        all_prompts_resp = (
            sb.table("geo_audit_prompts")
            .select("*")
            .eq("audit_id", audit_id)
            .order("prompt_id")
            .execute()
        )
        prompt_types = {p["prompt_id"]: p.get("prompt_type", "ranking") for p in all_prompts_resp.data}
        for r in all_result_rows:
            r["prompt_type"] = prompt_types.get(r["prompt_id"], "ranking")

        # Convert to AuditResult objects for summary generation
        all_audit_results = [
            AuditResult(
                prompt_id=r["prompt_id"],
                category=r["category"],
                prompt_text=r["prompt_text"],
                engine=r["engine"],
                brand_mentioned=r["brand_mentioned"],
                position_rank=r["position_rank"],
                url_cited=r["url_cited"],
                competitor_mentions=r.get("competitor_mentions", []),
                sentiment=r.get("sentiment", "neutral"),
                response_text=r.get("response_text", ""),
            )
            for r in all_result_rows
        ]

        summary = generate_summary_dict(all_audit_results, params["brand_name"], params.get("brand_url", ""))

        # Re-run analysis modules on full dataset
        logger.info(f"Extension {audit_id}: Running analysis on full dataset ({len(all_result_rows)} results)")

        keyword_gaps = analyse_keyword_gaps(
            results=all_result_rows,
            brand=params["brand_name"],
            competitors=params["competitors"],
        )
        summary["keyword_gap_analysis"] = keyword_gaps

        directory_results = check_directories(params["brand_name"])
        summary["directory_citations"] = directory_results

        # Load all prompts for SERP analysis
        all_prompts_resp = (
            sb.table("geo_audit_prompts")
            .select("*")
            .eq("audit_id", audit_id)
            .order("prompt_id")
            .execute()
        )
        prompt_dicts = [
            {"prompt_id": p["prompt_id"], "prompt_text": p["prompt_text"]}
            for p in all_prompts_resp.data
        ]

        site_index = check_site_index(params["brand_url"])
        organic_rankings = check_organic_rankings(prompt_dicts, params["brand_url"])
        serp_comparison = compare_ai_vs_seo(all_result_rows, organic_rankings)
        summary["serp_analysis"] = {
            "site_indexed": site_index,
            "organic_rankings": organic_rankings,
            "comparisons": serp_comparison["comparisons"],
            "summary": serp_comparison["summary"],
        }

        alice_brief = generate_alice_brief(
            results=all_result_rows,
            keyword_gaps=keyword_gaps,
            directory_results=directory_results,
            serp_data=serp_comparison,
            brand=params["brand_name"],
            competitors=params["competitors"],
        )
        summary["alice_brief"] = alice_brief

        try:
            sb.table("geo_alice_briefs").insert({
                "audit_id": audit_id,
                "client_name": params["brand_name"],
                "brief_json": alice_brief,
                "status": "pending",
            }).execute()
        except Exception as brief_exc:
            logger.warning(f"Failed to insert Alice brief: {brief_exc}")

        # Regenerate dashboard HTML
        dashboard_html = render_dashboard_from_data(
            rows=all_result_rows,
            client_name=params["brand_name"],
            client_url=params["brand_url"],
            template_path=TEMPLATE_PATH,
            keywords=params.get("keywords", []),
        )
        filename = f"{audit_id}/dashboard.html"
        sb.storage.from_("geo-dashboards").upload(
            filename,
            dashboard_html.encode("utf-8"),
            file_options={"content-type": "text/html", "upsert": "true"},
        )

        # Mark complete with updated totals
        elapsed = int(time.time() - start_time)
        sb.table("geo_audits").update({
            "status": "completed",
            "summary_json": summary,
            "visibility_rate": summary["overall_visibility"]["visibility_rate_percent"],
            "total_queries": summary["audit_metadata"]["total_queries"],
            "total_mentioned": summary["overall_visibility"]["brand_mentioned_count"],
            "progress_current": total,
            "progress_message": "Extended audit complete!",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()

        logger.info(
            f"Extension {audit_id} completed in {elapsed}s. "
            f"Total results: {len(all_result_rows)}, "
            f"Visibility: {summary['overall_visibility']['visibility_rate_percent']}%"
        )

    except Exception as exc:
        logger.exception(f"Extension {audit_id} failed: {exc}")
        # Revert to completed — original data is still intact
        sb.table("geo_audits").update({
            "status": "completed",
            "progress_message": f"Extension failed: {str(exc)[:200]}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", audit_id).execute()


def _mark_failed(sb, audit_id: str, error_message: str) -> None:
    """Mark an audit as failed with an error message."""
    sb.table("geo_audits").update({
        "status": "failed",
        "error_message": f"System crash: {error_message[:2000]}",
        "progress_message": f"Failed: {error_message[:200]}",
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", audit_id).execute()
