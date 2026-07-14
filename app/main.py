"""
FastAPI entry point for the GEO Audit Worker.

Endpoints:
    GET  /api/health         — Health check
    POST /api/audits/start   — Trigger a background audit task
"""

from __future__ import annotations

import logging
import smtplib
import asyncio
from contextlib import asynccontextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from .config import WORKER_API_KEY
from .worker import run_audit_task, run_audit_extension
from engine.generate_prompts import generate_wizard_prompts

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


class GeneratePromptsRequest(BaseModel):
    brand_name: str
    brand_url: str
    competitors: list[str] = []
    keywords: list[str] = []


class GeneratePromptsResponse(BaseModel):
    intent_prompts: list[str]
    ranking_prompts: list[str]


class SendInviteRequest(BaseModel):
    email: str
    agency_name: str
    password: str
    login_url: str


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


def _send_invite_email(to: str, agency_name: str, password: str, login_url: str):
    """Synchronous SMTP send — called via asyncio.to_thread."""
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    if not all([smtp_host, smtp_user, smtp_pass]):
        raise ValueError("SMTP_HOST, SMTP_USER and SMTP_PASS env vars are required.")

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:40px 0;">
        <tr><td align="center">
          <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
            <!-- Header -->
            <tr>
              <td style="background:linear-gradient(135deg,#0e1a2d,#1a2f4a);padding:32px 40px;text-align:center;">
                <div style="display:inline-block;background:linear-gradient(135deg,#5eead4,#2dd4bf);border-radius:10px;padding:10px 14px;margin-bottom:14px;">
                  <span style="font-size:22px;font-weight:900;color:#0e1a2d;letter-spacing:-1px;">G</span>
                </div>
                <div style="color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.5px;">Gatha</div>
                <div style="color:#5eead4;font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;margin-top:4px;">AI Visibility Platform</div>
              </td>
            </tr>
            <!-- Body -->
            <tr>
              <td style="padding:36px 40px;">
                <p style="margin:0 0 8px;font-size:22px;font-weight:700;color:#0e1a2d;">Welcome to Gatha, {agency_name}!</p>
                <p style="margin:0 0 28px;font-size:14px;color:#64748b;line-height:1.6;">
                  Your agency account is ready. Use the credentials below to log in and start running AI visibility audits.
                </p>

                <!-- Credentials box -->
                <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:28px;">
                  <tr>
                    <td style="padding:20px 24px;">
                      <div style="margin-bottom:14px;">
                        <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#94a3b8;margin-bottom:4px;">Login URL</div>
                        <div style="font-size:14px;color:#0e1a2d;font-weight:600;">{login_url}</div>
                      </div>
                      <div style="margin-bottom:14px;">
                        <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#94a3b8;margin-bottom:4px;">Email</div>
                        <div style="font-size:14px;color:#0e1a2d;font-weight:600;">{to}</div>
                      </div>
                      <div>
                        <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#94a3b8;margin-bottom:4px;">Temporary Password</div>
                        <div style="font-size:16px;color:#0e1a2d;font-weight:700;font-family:monospace;background:#fff;border:1px solid #e2e8f0;border-radius:6px;padding:8px 12px;display:inline-block;">{password}</div>
                      </div>
                    </td>
                  </tr>
                </table>

                <a href="{login_url}" style="display:inline-block;background:linear-gradient(135deg,#5eead4,#2dd4bf);color:#0e1a2d;font-weight:700;font-size:14px;text-decoration:none;padding:13px 28px;border-radius:8px;">
                  Log in to Gatha →
                </a>

                <p style="margin:28px 0 0;font-size:12px;color:#94a3b8;line-height:1.6;">
                  Please change your password after your first login. If you have any questions, reply to this email.
                </p>
              </td>
            </tr>
            <!-- Footer -->
            <tr>
              <td style="padding:20px 40px;background:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;">
                <p style="margin:0;font-size:11px;color:#94a3b8;">© Gatha · AI Search Visibility Platform</p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Welcome to Gatha — your login details"
    msg["From"] = smtp_from
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_from, [to], msg.as_string())


@app.post("/api/send-invite")
async def send_invite(
    req: SendInviteRequest,
    authorization: str = Header(...),
):
    """Send a welcome email with login credentials to a newly created agency."""
    api_key = os.environ.get("WORKER_API_KEY", "") or WORKER_API_KEY
    if not api_key or authorization != f"Bearer {api_key}":
        raise HTTPException(status_code=401, detail="Invalid worker API key.")

    try:
        await asyncio.to_thread(
            _send_invite_email,
            req.email,
            req.agency_name,
            req.password,
            req.login_url,
        )
        logger.info(f"Invite email sent to {req.email}")
        return {"ok": True}
    except Exception as e:
        logger.error(f"Failed to send invite email to {req.email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


@app.post("/api/generate-prompts", response_model=GeneratePromptsResponse)
async def generate_prompts(
    req: GeneratePromptsRequest,
    authorization: str = Header(...)
):
    """Generate 5 intent prompts and 10 ranking prompts using LLM"""
    api_key = os.environ.get("WORKER_API_KEY", "") or WORKER_API_KEY
    expected = f"Bearer {api_key}"
    if not api_key or authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid worker API key.")

    try:
        result = generate_wizard_prompts(
            brand_name=req.brand_name,
            brand_url=req.brand_url,
            competitors=req.competitors,
            keywords=req.keywords
        )
        return GeneratePromptsResponse(
            intent_prompts=result.get("intent_prompts", []),
            ranking_prompts=result.get("ranking_prompts", [])
        )
    except Exception as e:
        logger.error(f"Error generating prompts endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
