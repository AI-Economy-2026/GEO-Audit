"""
FastAPI entry point for the GEO Audit Worker.

Endpoints:
    GET  /api/health         — Health check
    POST /api/audits/start   — Trigger a background audit task
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

import os

from app.config import WORKER_API_KEY
from app.worker import run_audit_task, run_audit_extension

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GEO Audit Worker starting up...")
    yield
    logger.info("GEO Audit Worker shutting down.")


app = FastAPI(
    title="GEO Audit Worker",
    description="Background worker for running GEO visibility audits",
    version="1.0.0",
    lifespan=lifespan,
)


class AuditStartRequest(BaseModel):
    audit_id: str


class AuditExtendRequest(BaseModel):
    audit_id: str
    prompt_ids: list[int]


class HealthResponse(BaseModel):
    status: str
    service: str


class AuditStartResponse(BaseModel):
    status: str
    audit_id: str


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Health check endpoint for Railway."""
    return HealthResponse(status="ok", service="geo-audit-worker")


@app.get("/api/debug-env")
async def debug_env():
    """Temporary: check which env vars are loaded."""
    key = os.environ.get("WORKER_API_KEY", "")
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "worker_key_length": len(key),
        "worker_key_first5": key[:5] if key else "EMPTY",
        "supabase_url": sb_url[:40] if sb_url else "EMPTY",
        "supabase_key_length": len(sb_key),
        "supabase_key_first10": sb_key[:10] if sb_key else "EMPTY",
        "supabase_key_last5": sb_key[-5:] if sb_key else "EMPTY",
    }


@app.post("/api/audits/start", response_model=AuditStartResponse)
async def start_audit(
    req: AuditStartRequest,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...),
):
    """
    Trigger a background audit task.

    The caller must provide a valid Bearer token matching WORKER_API_KEY.
    The audit_id must already exist in the geo_audits table.
    """
    # Verify shared secret (read at request time to pick up Railway env vars)
    api_key = os.environ.get("WORKER_API_KEY", "") or WORKER_API_KEY
    expected = f"Bearer {api_key}"
    if not api_key or authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid worker API key.")

    logger.info(f"Received audit start request: {req.audit_id}")

    # Launch background task
    background_tasks.add_task(run_audit_task, req.audit_id)

    return AuditStartResponse(status="accepted", audit_id=req.audit_id)


@app.post("/api/audits/extend", response_model=AuditStartResponse)
async def extend_audit(
    req: AuditExtendRequest,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...),
):
    """Run additional prompts for an existing audit (incremental extension)."""
    api_key = os.environ.get("WORKER_API_KEY", "") or WORKER_API_KEY
    expected = f"Bearer {api_key}"
    if not api_key or authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid worker API key.")

    logger.info(f"Received extend request: {req.audit_id}, prompts: {req.prompt_ids}")
    background_tasks.add_task(run_audit_extension, req.audit_id, req.prompt_ids)
    return AuditStartResponse(status="accepted", audit_id=req.audit_id)
