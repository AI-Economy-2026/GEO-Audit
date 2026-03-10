"""
Background audit worker.

Receives an audit_id, loads params from Supabase, runs the audit engine,
writes results and progress back to Supabase, generates the dashboard HTML,
and uploads it to Supabase Storage.
"""

from __future__ import annotations

import logging
import os
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.supabase_client import get_supabase
from engine.geo_audit_engine import (
    AuditResult,
    ENGINE_DISPLAY_NAMES,
    Prompt,
    generate_summary_dict,
    run_audit,
)
from engine.generate_dashboard import render_dashboard_from_data

logger = logging.getLogger(__name__)

# Path to the bundled template
TEMPLATE_PATH = str(Path(__file__).resolve().parent.parent / "engine" / "geo-dashboard-template.html")


def run_audit_task(audit_id: str) -> None:
    """
    Execute a full GEO audit as a background task.

    1. Load audit params + prompts from Supabase
    2. Mark as running
    3. Query each engine for each prompt (with progress updates)
    4. Generate dashboard HTML
    5. Upload to Supabase Storage
    6. Mark as completed with summary stats
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

        # 3. Run audit with progress callback
        all_result_rows: list[dict] = []

        def on_progress(completed: int, total_count: int, result: AuditResult) -> None:
            # Check for cancellation periodically (every 10 queries)
            if completed % 10 == 0:
                check = sb.table("geo_audits").select("status").eq("id", audit_id).single().execute()
                if check.data["status"] == "cancelled":
                    raise InterruptedError("Audit was cancelled.")

            engine_display = ENGINE_DISPLAY_NAMES.get(result.engine, result.engine)

            # Insert individual result row
            row_data = {
                "audit_id": audit_id,
                "prompt_id": result.prompt_id,
                "category": result.category,
                "prompt_text": result.prompt_text,
                "engine": result.engine,
                "engine_display": engine_display,
                "brand_mentioned": result.brand_mentioned,
                "position_rank": result.position_rank,
                "url_cited": result.url_cited,
                "competitor_mentions": result.competitor_mentions,
                "sentiment": result.sentiment,
                "response_text": result.response_text[:10000],  # cap at 10k chars
            }
            sb.table("geo_audit_results").insert(row_data).execute()

            # Also store for dashboard generation
            all_result_rows.append(row_data)

            # Update progress on audit row (triggers Supabase Realtime)
            mention_str = "mentioned" if result.brand_mentioned else "not mentioned"
            sb.table("geo_audits").update({
                "progress_current": completed,
                "progress_message": (
                    f"[{completed}/{total_count}] {engine_display} — "
                    f"Prompt #{result.prompt_id}: {mention_str}"
                ),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", audit_id).execute()

        results = run_audit(
            prompts=prompts,
            brand=params["brand_name"],
            url=params["brand_url"],
            competitors=params["competitors"],
            engines=engines,
            progress_callback=on_progress,
        )

        # 4. Generate dashboard HTML
        dashboard_html = render_dashboard_from_data(
            rows=all_result_rows,
            client_name=params["brand_name"],
            client_url=params["brand_url"],
            template_path=TEMPLATE_PATH,
        )

        # 5. Upload to Supabase Storage
        filename = f"{audit_id}/dashboard.html"
        sb.storage.from_("geo-dashboards").upload(
            filename,
            dashboard_html.encode("utf-8"),
            file_options={"content-type": "text/html"},
        )
        dashboard_url = sb.storage.from_("geo-dashboards").get_public_url(filename)

        # 6. Generate summary and mark complete
        summary = generate_summary_dict(results, params["brand_name"])
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


def _mark_failed(sb, audit_id: str, error_message: str) -> None:
    """Mark an audit as failed with an error message."""
    sb.table("geo_audits").update({
        "status": "failed",
        "error_message": error_message[:2000],
        "progress_message": f"Failed: {error_message[:200]}",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", audit_id).execute()
