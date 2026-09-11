"""GET /api/admin/finance — cost-vs-income dashboard data for super-admins.

Returns KPIs (total revenue, total cost, margin), a per-agency breakdown,
and a monthly trend series.  All amounts are in cents (AUD).

Income comes from billing_transactions.amount_cents.
Cost comes from audit_costs.cost_cents (logged by the worker when an audit
completes).  If audit_costs is empty (no audits logged yet), cost is 0 and
the dashboard still shows revenue from Stripe payments.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from fastapi import APIRouter, HTTPException

from .supabase_client import get_supabase

router = APIRouter()


def _parse_date_range(from_str: str | None, to_str: str | None) -> tuple[str, str]:
    """Return (from_iso, to_iso) clamped to a sane range."""
    today = _dt.date.today()
    default_from = today - _dt.timedelta(days=365)
    try:
        d_from = _dt.date.fromisoformat(from_str) if from_str else default_from
    except ValueError:
        d_from = default_from
    try:
        d_to = _dt.date.fromisoformat(to_str) if to_str else today
    except ValueError:
        d_to = today
    if d_to < d_from:
        d_from, d_to = d_to, d_from
    # Inclusive end → add 1 day so the upper bound is exclusive in SQL.
    return d_from.isoformat(), (d_to + _dt.timedelta(days=1)).isoformat()


@router.get("/api/admin/finance")
def admin_finance(from_: str | None = None, to: str | None = None) -> dict[str, Any]:
    """Aggregate revenue + cost for the finance dashboard."""
    from_iso, to_iso = _parse_date_range(from_, to)
    sb = get_supabase()

    # ── Revenue per agency ──────────────────────────────────────────
    rev_rows = (
        sb.table("billing_transactions")
        .select("user_id, amount_cents, created_at")
        .gte("created_at", from_iso)
        .lt("created_at", to_iso)
        .execute()
    ).data or []

    revenue_by_user: dict[str, int] = {}
    for r in rev_rows:
        uid = r.get("user_id")
        if not uid:
            continue
        revenue_by_user[uid] = revenue_by_user.get(uid, 0) + (r.get("amount_cents") or 0)

    # ── Cost per agency ─────────────────────────────────────────────
    cost_rows = (
        sb.table("audit_costs")
        .select("user_id, cost_cents, created_at")
        .gte("created_at", from_iso)
        .lt("created_at", to_iso)
        .execute()
    ).data or []

    cost_by_user: dict[str, int] = {}
    for r in cost_rows:
        uid = r.get("user_id")
        if not uid:
            continue
        cost_by_user[uid] = cost_by_user.get(uid, 0) + (r.get("cost_cents") or 0)

    # ── Audit counts per agency ─────────────────────────────────────
    audit_rows = (
        sb.table("geo_audits")
        .select("created_by, created_at")
        .gte("created_at", from_iso)
        .lt("created_at", to_iso)
        .execute()
    ).data or []
    audits_by_user: dict[str, int] = {}
    for r in audit_rows:
        uid = r.get("created_by")
        if not uid:
            continue
        audits_by_user[uid] = audits_by_user.get(uid, 0) + 1

    # ── Agency metadata ─────────────────────────────────────────────
    all_uids = set(revenue_by_user) | set(cost_by_user) | set(audits_by_user)
    agencies: list[dict[str, Any]] = []
    if all_uids:
        user_rows = (
            sb.table("app_users")
            .select("id, email, agency_name, credits_used")
            .in_("id", list(all_uids))
            .execute()
        ).data or []
        for u in user_rows:
            uid = u["id"]
            rev = revenue_by_user.get(uid, 0)
            cost = cost_by_user.get(uid, 0)
            margin = rev - cost
            margin_pct = round(margin / rev * 100, 1) if rev > 0 else 0.0
            agencies.append({
                "user_id": uid,
                "agency_name": u.get("agency_name") or u.get("email") or "—",
                "email": u.get("email") or "",
                "revenue_cents": rev,
                "cost_cents": cost,
                "margin_cents": margin,
                "margin_pct": margin_pct,
                "audits_run": audits_by_user.get(uid, 0),
                "credits_used": u.get("credits_used") or 0,
            })

    # Sort by revenue descending
    agencies.sort(key=lambda a: a["revenue_cents"], reverse=True)

    # ── Monthly trend ───────────────────────────────────────────────
    monthly_map: dict[str, dict[str, int]] = {}
    for r in rev_rows:
        if not r.get("created_at"):
            continue
        month = r["created_at"][:7]  # YYYY-MM
        m = monthly_map.setdefault(month, {"revenue_cents": 0, "cost_cents": 0, "audits": 0})
        m["revenue_cents"] += r.get("amount_cents") or 0
    for r in cost_rows:
        if not r.get("created_at"):
            continue
        month = r["created_at"][:7]
        m = monthly_map.setdefault(month, {"revenue_cents": 0, "cost_cents": 0, "audits": 0})
        m["cost_cents"] += r.get("cost_cents") or 0
    for r in audit_rows:
        if not r.get("created_at"):
            continue
        month = r["created_at"][:7]
        m = monthly_map.setdefault(month, {"revenue_cents": 0, "cost_cents": 0, "audits": 0})
        m["audits"] += 1
    monthly = [
        {"month": k, **v}
        for k, v in sorted(monthly_map.items())
    ]

    # ── KPIs ─────────────────────────────────────────────────────────
    total_rev = sum(a["revenue_cents"] for a in agencies)
    total_cost = sum(a["cost_cents"] for a in agencies)
    total_margin = total_rev - total_cost
    total_audits = sum(a["audits_run"] for a in agencies)
    margin_pct = round(total_margin / total_rev * 100, 1) if total_rev > 0 else 0.0
    avg_cost_per_audit = round(total_cost / total_audits) if total_audits > 0 else 0

    return {
        "kpis": {
            "total_revenue_cents": total_rev,
            "total_cost_cents": total_cost,
            "total_margin_cents": total_margin,
            "margin_pct": margin_pct,
            "audits_run": total_audits,
            "avg_cost_per_audit_cents": avg_cost_per_audit,
        },
        "agencies": agencies,
        "monthly": monthly,
    }
