"""
FastAPI entry point for the GEO Audit Worker.

Endpoints:
    GET  /api/health         - Health check
    POST /api/audits/start   - Trigger a background audit task
"""

from __future__ import annotations

import hmac
import logging
import smtplib
import asyncio
import uuid
from contextlib import asynccontextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import stripe

from .config import WORKER_API_KEY
from .mcp_server import router as mcp_router
from .worker import run_audit_task, run_audit_extension
from . import billing
from .watches import tick_due_watches
from .webhooks import deliver_event
from .integrations_worker import send_to_integration
from engine.generate_prompts import generate_wizard_prompts
from engine.providers.serp import SerpCapability, get_serp_provider, provider_status
from engine.providers.serp._http import clean_domain

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _opaque_error(
    exc: Exception,
    context: str,
    status_code: int = 500,
    message: str = "Internal server error.",
) -> HTTPException:
    """Log an exception against a short correlation id, return a safe error.

    Exception text here can carry SMTP banners, upstream API payloads, stack
    context and configuration detail, none of which belongs in a response
    body. The caller gets only the reference so it can be quoted in a support
    request and matched to the log line.
    """
    correlation_id = uuid.uuid4().hex[:12]
    logger.exception("[%s] %s: %s", correlation_id, context, exc)
    return HTTPException(
        status_code=status_code,
        detail=f"{message} Reference: {correlation_id}",
    )


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

# Mount the MCP tool endpoints (auth via per-agency MCP API keys, not worker auth)
app.include_router(mcp_router)


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


class CheckoutRequest(BaseModel):
    user_id: str
    product_type: str
    product_id: str
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    url: str


def require_worker_auth(authorization: str = Header(...)) -> None:
    """Verify the shared worker secret on the Authorization header.

    Read at request time so a redeployed env var is picked up without a
    restart. Uses a constant-time comparison so a wrong key cannot be
    recovered by timing the response.
    """
    api_key = os.environ.get("WORKER_API_KEY", "") or WORKER_API_KEY
    if not api_key:
        logger.error("WORKER_API_KEY is not configured; rejecting request.")
        raise HTTPException(status_code=500, detail="Worker auth is not configured.")

    if not hmac.compare_digest(authorization, f"Bearer {api_key}"):
        raise HTTPException(status_code=401, detail="Invalid worker API key.")


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Health check endpoint for Railway."""
    return HealthResponse(status="ok", service="geo-audit-worker")


def _send_invite_email(to: str, agency_name: str, password: str, login_url: str):
    """Synchronous SMTP send, called via asyncio.to_thread."""
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
    msg["Subject"] = f"Welcome to Gatha: your login details"
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
    _: None = Depends(require_worker_auth),
):
    """Send a welcome email with login credentials to a newly created agency.

    Auth goes through require_worker_auth like every other protected route.
    This endpoint used to compare the header with `!=`, which leaks the key a
    character at a time to anyone who can time the response, and it also
    skipped the "key not configured" guard that returns 500 rather than 401.
    """

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
        raise _opaque_error(
            e,
            f"Failed to send invite email to {req.email}",
            message="Could not send the invite email.",
        )


@app.post("/api/generate-prompts", response_model=GeneratePromptsResponse)
async def generate_prompts(
    req: GeneratePromptsRequest,
    _: None = Depends(require_worker_auth),
):
    """Generate 5 intent prompts and 10 ranking prompts using LLM"""
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
        raise _opaque_error(
            e,
            "Error generating prompts endpoint",
            message="Could not generate prompts.",
        )


@app.post("/api/audits/start", response_model=AuditStartResponse)
async def start_audit(
    req: AuditStartRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_worker_auth),
):
    """
    Trigger a background audit task.

    The caller must provide a valid Bearer token matching WORKER_API_KEY.
    The audit_id must already exist in the geo_audits table.
    """
    logger.info(f"Received audit start request: {req.audit_id}")

    # Launch background task
    background_tasks.add_task(run_audit_task, req.audit_id)

    return AuditStartResponse(status="accepted", audit_id=req.audit_id)


@app.post("/api/audits/extend", response_model=AuditStartResponse)
async def extend_audit(
    req: AuditExtendRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_worker_auth),
):
    """Run additional prompts for an existing audit (incremental extension)."""
    logger.info(f"Received extend request: {req.audit_id}, prompts: {req.prompt_ids}")
    background_tasks.add_task(run_audit_extension, req.audit_id, req.prompt_ids)
    return AuditStartResponse(status="accepted", audit_id=req.audit_id)


@app.post("/api/checkout", response_model=CheckoutResponse)
async def create_checkout(
    req: CheckoutRequest,
    _: None = Depends(require_worker_auth),
):
    """
    Create a Stripe Checkout session and return its hosted URL.

    Called by the Next.js app's /api/checkout proxy route, which has already
    authenticated the browser session and supplies the resolved user_id.
    Uses the same worker-auth Bearer scheme as /api/audits/start: Python
    trusts the Next.js backend, not the browser.
    """
    try:
        url = billing.create_checkout_session(
            user_id=req.user_id,
            product_type=req.product_type,
            product_id=req.product_id,
            success_url=req.success_url,
            cancel_url=req.cancel_url,
        )
        return CheckoutResponse(url=url)
    except ValueError as e:
        # str(e) here comes from the billing layer and can name internal
        # product identifiers and configuration state. Same treatment as
        # every other error path: correlation id out, detail into the log.
        raise _opaque_error(
            e,
            "Rejected checkout session request",
            status_code=400,
            message="That purchase could not be started.",
        )
    except Exception as e:
        raise _opaque_error(
            e,
            "Failed to create checkout session",
            message="Could not create the checkout session.",
        )


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook receiver. Called directly by Stripe (or the `stripe
    listen` CLI forwarder in local dev), NOT through the worker-auth Bearer
    scheme. Verifies the Stripe webhook signature instead.
    """
    signature = request.headers.get("stripe-signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not signature or not webhook_secret:
        raise HTTPException(status_code=500, detail="Webhook is not configured.")

    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except Exception as e:
        raise _opaque_error(
            e,
            "Stripe webhook signature verification failed",
            status_code=400,
            message="Webhook signature verification failed.",
        )

    try:
        if event["type"] == "checkout.session.completed":
            billing.fulfill_checkout_session(event)
        elif event["type"] == "checkout.session.async_payment_succeeded":
            # A delayed-notification method (bank debit, some wallets) finally
            # paid. completed fired earlier with payment_status unpaid and was
            # skipped, so this is where that purchase actually gets fulfilled.
            billing.fulfill_checkout_session(event)
        elif event["type"] == "checkout.session.async_payment_failed":
            logger.warning(
                "Checkout session %s failed to pay after completing (event %s); nothing granted.",
                event["data"]["object"].get("id") if hasattr(event["data"]["object"], "get") else "?",
                event["id"],
            )
        elif event["type"] in ("charge.refunded", "charge.dispute.created"):
            # No clawback exists: credits_remaining has a CHECK (>= 0) and the
            # spend paths floor at zero, so a refund after the credits are
            # spent cannot be represented. Surface it loudly so it is handled
            # by hand rather than silently absorbed.
            logger.error(
                "MANUAL ACTION: Stripe %s received (event %s). Credits are not clawed back "
                "automatically; adjust the agency's balance from the admin panel.",
                event["type"],
                event["id"],
            )
    except Exception as e:
        raise _opaque_error(
            e,
            f"Stripe webhook fulfillment failed for event {event['id']}",
            message="Could not process the webhook event.",
        )

    return {"received": True}


class KeywordIdeasRequest(BaseModel):
    brand_url: str
    country: str | None = None
    limit: int = 50


@app.post("/api/seo/keyword-ideas")
async def seo_keyword_ideas(
    req: KeywordIdeasRequest,
    _: None = Depends(require_worker_auth),
):
    """Return keyword ideas for a domain (DataForSEO when configured)."""
    provider = get_serp_provider(SerpCapability.KEYWORD_IDEAS)
    if not provider.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Keyword ideas are unavailable. DataForSEO is not configured.",
        )
    try:
        data = provider.keyword_ideas(
            clean_domain(req.brand_url),
            country=req.country,
            limit=min(max(req.limit, 1), 100),
        )
        if data.get("error") and data.get("error") != "provider_unavailable":
            raise RuntimeError(data.get("error"))
        return {
            "keywords": data.get("keywords") or [],
            "provider": data.get("provider"),
            "providers": provider_status(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise _opaque_error(e, "keyword-ideas failed", message="Could not load keyword ideas.")


@app.post("/api/watches/tick")
async def watches_tick(
    background_tasks: BackgroundTasks,
    _: None = Depends(require_worker_auth),
):
    """Cron entrypoint: process due Watch schedules."""
    try:
        # Run synchronously for cron reliability; each audit is already a full job.
        result = tick_due_watches()
        return {"status": "ok", **result}
    except Exception as e:
        raise _opaque_error(e, "watches tick failed", message="Could not process watches.")


class DeliverWebhookRequest(BaseModel):
    user_id: str
    event: str
    payload: dict


class IntegrationSendRequest(BaseModel):
    service: str
    audit_id: str
    user_id: str


@app.post("/api/webhooks/deliver")
async def webhooks_deliver(
    req: DeliverWebhookRequest,
    _: None = Depends(require_worker_auth),
):
    try:
        count = deliver_event(req.user_id, req.event, req.payload)
        return {"delivered": count}
    except Exception as e:
        raise _opaque_error(e, "webhook deliver failed", message="Could not deliver webhooks.")


@app.get("/api/providers/status")
async def providers_status(_: None = Depends(require_worker_auth)):
    return provider_status()


@app.get("/api/engines/available")
async def engines_available(_: None = Depends(require_worker_auth)):
    """Return the list of engines that have their required API keys configured."""
    from engine.geo_audit_engine import ENGINE_KEY_MAP
    available = []
    for engine_name, env_key in ENGINE_KEY_MAP.items():
        if os.environ.get(env_key, "").strip():
            available.append(engine_name)
    return {"engines": available, "providers": provider_status()}


@app.get("/api/gsc/sites")
async def gsc_sites(req: Request, _: None = Depends(require_worker_auth)):
    """List GSC properties for a user."""
    from app.gsc import list_sites
    user_id = req.query_params.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        return list_sites(user_id)
    except Exception as e:
        raise _opaque_error(e, "GSC sites list failed", message="Could not list GSC properties.")


@app.post("/api/gsc/search-analytics")
async def gsc_search_analytics(req: Request, _: None = Depends(require_worker_auth)):
    """Query GSC Search Analytics for a user's property."""
    from app.gsc import query_search_analytics
    body = await req.json()
    user_id = body.get("user_id", "")
    site_url = body.get("site_url", "")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    row_limit = body.get("row_limit", 100)
    if not user_id or not site_url:
        raise HTTPException(status_code=400, detail="user_id and site_url are required")
    try:
        return query_search_analytics(user_id, site_url, start_date, end_date, row_limit)
    except Exception as e:
        raise _opaque_error(e, "GSC search analytics failed", message="Could not query GSC data.")


@app.get("/api/ga4/properties")
async def ga4_properties(req: Request, _: None = Depends(require_worker_auth)):
    """List GA4 properties for a user."""
    from app.ga4 import list_properties
    user_id = req.query_params.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        return list_properties(user_id)
    except Exception as e:
        raise _opaque_error(e, "GA4 properties list failed", message="Could not list GA4 properties.")


# ---------------------------------------------------------------------------
# Integrations — send + proxy lookups (Notion / Asana / Slack / GHL)
# ---------------------------------------------------------------------------


@app.post("/api/integrations/send")
async def integrations_send(
    req: IntegrationSendRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_worker_auth),
):
    """Enqueue an integration send as a background task.

    Returns immediately with a job_id; the actual send runs in a
    BackgroundTask and never raises into the request lifecycle.
    """
    job_id = str(uuid.uuid4())
    background_tasks.add_task(
        send_to_integration,
        req.service,
        req.audit_id,
        req.user_id,
    )
    return {"status": "queued", "job_id": job_id}


def _lookup_integration_credential(user_id: str, service: str) -> str:
    """Look up a user's connected integration and decrypt its credential."""
    from .supabase_client import get_supabase
    from .encryption import decrypt_token

    sb = get_supabase()
    integration = (
        sb.table("agency_integrations")
        .select("credential_enc")
        .eq("user_id", user_id)
        .eq("service", service)
        .eq("status", "connected")
        .maybeSingle()
        .execute()
    ).data
    if not integration:
        raise HTTPException(
            status_code=404,
            detail=f"No connected {service} integration for this user.",
        )
    return decrypt_token(integration["credential_enc"])


@app.get("/api/ghl/contacts")
async def ghl_contacts(
    search: str = "",
    page: int = 1,
    user_id: str = "",
    _: None = Depends(require_worker_auth),
):
    """Fetch contacts from GHL for the client picker."""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    try:
        api_key = _lookup_integration_credential(user_id, "ghl")
    except HTTPException:
        raise
    except Exception as e:
        raise _opaque_error(e, "GHL credential lookup failed", message="Could not load GHL credentials.")

    import urllib.request
    import urllib.parse
    import json as _json

    limit = 20
    skip = (page - 1) * limit
    qs = urllib.parse.urlencode({
        "query": search,
        "limit": limit,
        "skip": skip,
    })
    req = urllib.request.Request(
        f"https://rest.gohighlevel.com/v1/contacts?{qs}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise _opaque_error(e, "GHL contacts fetch failed", message="Could not fetch GHL contacts.")

    contacts = []
    for c in data.get("contacts") or []:
        first = c.get("firstName", "") or ""
        last = c.get("lastName", "") or ""
        name = f"{first} {last}".strip() or c.get("name", "")
        contacts.append({
            "id": c.get("id"),
            "name": name,
            "email": c.get("email"),
            "phone": c.get("phone"),
            "company_name": c.get("companyName") or c.get("company_name"),
            "website": c.get("website"),
        })

    total = data.get("count") or len(contacts)
    has_more = skip + len(contacts) < total
    return {"contacts": contacts, "total": total, "has_more": has_more}


@app.get("/api/notion/databases")
async def notion_databases(
    user_id: str = "",
    _: None = Depends(require_worker_auth),
):
    """List Notion databases for the database selector."""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    try:
        token = _lookup_integration_credential(user_id, "notion")
    except HTTPException:
        raise
    except Exception as e:
        raise _opaque_error(e, "Notion credential lookup failed", message="Could not load Notion credentials.")

    import urllib.request
    import json as _json

    req = urllib.request.Request(
        "https://api.notion.com/v1/databases",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise _opaque_error(e, "Notion databases fetch failed", message="Could not fetch Notion databases.")

    databases = []
    for db in data.get("results", []):
        # Notion titles are rich-text arrays
        title_parts = db.get("title", [])
        title = ""
        if isinstance(title_parts, list):
            title = "".join(
                t.get("plain_text", "") for t in title_parts if isinstance(t, dict)
            )
        databases.append({
            "id": db.get("id"),
            "title": title or "Untitled",
            "url": db.get("url"),
        })
    return {"databases": databases}


@app.get("/api/asana/workspaces")
async def asana_workspaces(
    user_id: str = "",
    _: None = Depends(require_worker_auth),
):
    """List Asana workspaces."""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    try:
        token = _lookup_integration_credential(user_id, "asana")
    except HTTPException:
        raise
    except Exception as e:
        raise _opaque_error(e, "Asana credential lookup failed", message="Could not load Asana credentials.")

    import urllib.request
    import json as _json

    req = urllib.request.Request(
        "https://app.asana.com/api/1.0/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise _opaque_error(e, "Asana workspaces fetch failed", message="Could not fetch Asana workspaces.")

    workspaces = [
        {"id": w.get("gid"), "name": w.get("name", "")}
        for w in data.get("data", [])
    ]
    return {"workspaces": workspaces}


@app.get("/api/asana/projects")
async def asana_projects(
    user_id: str = "",
    workspace_id: str = "",
    _: None = Depends(require_worker_auth),
):
    """List Asana projects in a workspace."""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")

    try:
        token = _lookup_integration_credential(user_id, "asana")
    except HTTPException:
        raise
    except Exception as e:
        raise _opaque_error(e, "Asana credential lookup failed", message="Could not load Asana credentials.")

    import urllib.request
    import urllib.parse
    import json as _json

    qs = urllib.parse.urlencode({"workspace": workspace_id, "limit": 50})
    req = urllib.request.Request(
        f"https://app.asana.com/api/1.0/projects?{qs}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise _opaque_error(e, "Asana projects fetch failed", message="Could not fetch Asana projects.")

    projects = [
        {"id": p.get("gid"), "name": p.get("name", "")}
        for p in data.get("data", [])
    ]
    return {"projects": projects}

