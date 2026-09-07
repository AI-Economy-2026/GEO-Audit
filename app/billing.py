"""
Stripe billing: checkout session creation + webhook fulfillment.

Product catalog, checkout-session shape (inline price_data, no pre-created
Stripe Price objects) and fulfilment semantics live here. White label was
removed from the catalogue: it was sold but never built, so nothing read the
flag it set.

Idempotency: fulfill_checkout_session() is guarded by the billing_transactions
table's UNIQUE(stripe_event_id) constraint (see supabase/160_billing_transactions.sql).
A duplicate webhook delivery for the same Stripe event either no-ops on the
pre-check, or fails the final insert with a unique-violation which is caught
and logged rather than raised.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import stripe

from .supabase_client import get_supabase, execute_with_retry

logger = logging.getLogger(__name__)

ProductType = str  # "tier" | "bundle"

# Audit tiers: one-off purchase. All three grant exactly +1 credit. NOTE that
# docs/mockups/Audit-Pricing-Ledger.html specifies real per-tier limits
# (Snapshot 25 prompts x 3 engines, Audit 50 x 5, Deep 100 x 5) which are NOT
# implemented anywhere: no tier is attached to an audit and every audit is
# capped at 30 prompts by the app's prompt generator. So $79 currently buys
# exactly what $19 buys. Flagged, not silently accepted.
AUDIT_TIERS: dict[str, dict[str, Any]] = {
    "snapshot": {"name": "Snapshot Audit", "amount_cents": 1900, "credits": 1},
    "standard": {"name": "Standard Audit", "amount_cents": 4900, "credits": 1},
    "deep": {"name": "Deep Audit", "amount_cents": 7900, "credits": 1},
}

# Bundle packs: one-off purchase, credits vary by pack. Legendary no longer
# carries a white-label perk; white label was sold but never built, so it has
# been removed from the catalogue entirely.
BUNDLE_PACKS: dict[str, dict[str, Any]] = {
    "starter": {"name": "Starter Pack", "amount_cents": 9900, "credits": 3},
    "growth": {"name": "Growth Pack", "amount_cents": 27900, "credits": 10},
    "legendary": {"name": "Legendary Pack", "amount_cents": 59900, "credits": 25},
}

# Stripe Tax product tax code. Required on every line item once Stripe Tax is
# active on the account, otherwise session creation is rejected. Defaults to
# "General - Electronically Supplied Services", which is also the account-level
# default Stripe reports for this account, and is overridable per environment.
STRIPE_TAX_CODE = os.environ.get("STRIPE_TAX_CODE", "txcd_10000000")


def _configure_stripe() -> None:
    """Read STRIPE_SECRET_KEY from env at call time (not import time) so this
    module can be imported freely without a key configured, and only raises
    once Stripe is actually used."""
    secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = secret_key


def _get_one_off_product(product_type: str, product_id: str) -> dict[str, Any]:
    catalog = AUDIT_TIERS if product_type == "tier" else BUNDLE_PACKS
    product = catalog.get(product_id)
    if not product:
        raise ValueError(f"Unknown {product_type} product: {product_id}")
    return product


def create_checkout_session(
    user_id: str,
    product_type: str,
    product_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session and return its hosted URL."""
    _configure_stripe()

    metadata = {"user_id": user_id, "product_type": product_type, "product_id": product_id or ""}

    if product_type in ("tier", "bundle"):
        product = _get_one_off_product(product_type, product_id)
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": product["amount_cents"],
                        "product_data": {
                            "name": product["name"],
                            "tax_code": STRIPE_TAX_CODE,
                        },
                    },
                    "quantity": 1,
                }
            ],
            metadata=metadata,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    else:
        raise ValueError(f"Unknown product type: {product_type}")

    if not session.url:
        raise RuntimeError("Stripe did not return a checkout session URL")
    return session.url


def _increment_credits(user_id: str, credits: int) -> None:
    """Add credits atomically.

    Uses the grant_credits function from supabase/180_billing_integrity.sql,
    which does the whole move in one statement. The old read-then-write could
    lose the grant entirely: a concurrent audit creation reading the balance
    before the grant and writing back after it erased the purchase, leaving a
    paid ledger row and no credits.

    Falls back to the read-then-write if 180 has not been applied yet, so a
    deploy ahead of the migration still grants rather than failing, but says
    so loudly because the race is back until the migration runs.
    """
    sb = get_supabase()
    try:
        execute_with_retry(
            lambda: sb.rpc("grant_credits", {"p_user_id": user_id, "p_credits": credits}).execute(),
            op="rpc grant_credits",
        )
        return
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if not ("grant_credits" in msg and ("does not exist" in msg or "not find" in msg or "404" in msg)):
            raise
        logger.error(
            "grant_credits RPC is missing; apply supabase/180_billing_integrity.sql. "
            "Falling back to a read-modify-write, which can lose a concurrent grant."
        )

    result = execute_with_retry(
        lambda: sb.table("app_users").select("credits_remaining").eq("id", user_id).maybe_single().execute(),
        op="fetch app_users.credits_remaining",
    )
    profile = result.data if result else None
    if not profile:
        raise RuntimeError(f"Cannot grant credits, app_users row not found for {user_id}")

    new_balance = (profile.get("credits_remaining") or 0) + credits
    execute_with_retry(
        lambda: sb.table("app_users")
        .update({"credits_remaining": new_balance, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", user_id)
        .execute(),
        op="update app_users.credits_remaining",
    )


def _extract_id(value: Any) -> Optional[str]:
    """Stripe fields like `customer`/`subscription` can be either an id
    string or an expanded object; normalize to a plain id string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    # `value` is either a plain dict (post to_dict() conversion) or a raw
    # StripeObject; StripeObject doesn't support .get() (hasattr(..., "get")
    # correctly comes back False for it), so fall back to attribute access.
    return value.get("id") if hasattr(value, "get") else getattr(value, "id", None)


def _record_unfulfillable(sb: Any, event_id: str, session_dict: dict, reason: str) -> None:
    """A session we cannot fulfil still has to leave a trace.

    Both of the early returns below hand Stripe a 2xx, so Stripe marks the
    event delivered and never mentions it again. Without a row here the
    money is taken and there is nothing anywhere to find it by.
    """
    try:
        execute_with_retry(
            lambda: sb.table("billing_transactions")
            .insert(
                {
                    "user_id": None,
                    "stripe_event_id": event_id,
                    "stripe_session_id": session_dict.get("id"),
                    "product_type": "unfulfillable",
                    "product_id": reason[:200],
                    "amount_cents": session_dict.get("amount_total"),
                    "credits_granted": 0,
                }
            )
            .execute(),
            op="record unfulfillable checkout session",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not record unfulfillable session for event %s (%s)", event_id, reason)


def fulfill_checkout_session(event: Any) -> None:
    """Called from the Stripe webhook on checkout.session.completed.

    Ordering matters here and is deliberate: the billing_transactions row is
    written BEFORE any credit is granted.

    The row's UNIQUE(stripe_event_id) is the only real idempotency guard, and
    it only guards what comes after it. Granting first meant that any failure
    between the grant and the insert raised, returned a 5xx, and Stripe
    retried the event, up to about fifteen times over three days; each retry
    found no ledger row, so each retry granted again. One Legendary purchase
    could have paid out hundreds of credits. Two deliveries arriving at once
    had the same effect through a different door: both passed the pre-check,
    both granted, and the loser's insert hit the unique violation, which was
    caught and ignored.

    Writing the row first inverts the failure. If the grant now fails, the
    customer has paid and is briefly short, which is visible (a row whose
    credits_granted does not match the balance movement) and fixable from the
    admin credit adjustment. That is recoverable; giving product away in an
    unbounded loop is not.
    """
    session = event["data"]["object"]
    event_id = event["id"]

    # Stripe SDK objects (StripeObject/Session/Event) only support subscript
    # access and .to_dict() — calling .get() on them raises AttributeError
    # ("... is not a dict. Use .to_dict() to convert it."). Convert once here
    # so the rest of this function can use normal dict semantics.
    session_dict = session.to_dict() if hasattr(session, "to_dict") else dict(session)

    sb = get_supabase()

    metadata = dict(session_dict.get("metadata") or {})
    user_id = metadata.get("user_id")
    product_type = metadata.get("product_type")
    product_id = metadata.get("product_id")

    if not user_id or not product_type:
        logger.error("Checkout session (event %s) missing user_id/product_type metadata", event_id)
        _record_unfulfillable(sb, event_id, session_dict, "missing user_id or product_type metadata")
        return

    # checkout.session.completed does NOT imply the money arrived. With cards
    # it effectively does, but any delayed-notification method (bank debits and
    # some wallets) completes the session first and pays later, arriving as
    # checkout.session.async_payment_succeeded. Fulfilling on an unpaid session
    # would hand over credits for a payment that may still fail.
    payment_status = session_dict.get("payment_status")
    if payment_status not in ("paid", "no_payment_required"):
        logger.info(
            "Checkout session %s (event %s) is not paid yet (payment_status=%s); not fulfilling",
            session_dict.get("id"),
            event_id,
            payment_status,
        )
        return

    # Resolve the product before writing anything, so an unrecognised product
    # never leaves a ledger row claiming credits it cannot describe.
    credits_to_grant = 0
    if product_type in ("tier", "bundle"):
        try:
            product = _get_one_off_product(product_type, product_id or "")
        except ValueError:
            logger.error("Unknown %s product %r in event %s", product_type, product_id, event_id)
            _record_unfulfillable(sb, event_id, session_dict, f"unknown {product_type} product: {product_id}")
            return
        credits_to_grant = product["credits"]
    else:
        logger.error("Unknown product type in checkout session metadata: %s", product_type)
        _record_unfulfillable(sb, event_id, session_dict, f"unknown product_type: {product_type}")
        return

    # Claim the event. A unique violation here means this event is already
    # fulfilled, by an earlier delivery or a concurrent one, so we must not
    # grant again. Any other error means nothing has been written and nothing
    # granted, so letting it raise is safe: Stripe retries a clean slate.
    try:
        execute_with_retry(
            lambda: sb.table("billing_transactions")
            .insert(
                {
                    "user_id": user_id,
                    "stripe_event_id": event_id,
                    "stripe_session_id": session_dict.get("id"),
                    "product_type": product_type,
                    "product_id": product_id,
                    "amount_cents": session_dict.get("amount_total"),
                    "credits_granted": credits_to_grant,
                }
            )
            .execute(),
            op="claim billing_transactions row",
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "duplicate key" in msg or "23505" in msg or "unique" in msg:
            logger.info("Stripe event %s already fulfilled, skipping", event_id)
            return
        raise

    # The row is ours, so this grant happens exactly once per Stripe event.
    _increment_credits(user_id, credits_to_grant)
    logger.info(
        "Fulfilled event %s: granted %d credit(s) to %s for %s/%s",
        event_id,
        credits_to_grant,
        user_id,
        product_type,
        product_id,
    )
