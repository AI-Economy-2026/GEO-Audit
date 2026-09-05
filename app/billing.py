"""
Stripe billing: checkout session creation + webhook fulfillment.

Ported from the Next.js app's src/services/billing-service.ts. The product
catalog, checkout-session shape (inline price_data, no pre-created Stripe
Price objects) and fulfillment semantics (grant credits / set
white_label_active) are kept identical to that TypeScript version.

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

ProductType = str  # "tier" | "bundle" | "white_label"

# Audit tiers: one-off purchase, each grants +1 credit regardless of tier.
AUDIT_TIERS: dict[str, dict[str, Any]] = {
    "snapshot": {"name": "Snapshot Audit", "amount_cents": 1900, "credits": 1, "grants_white_label": False},
    "standard": {"name": "Standard Audit", "amount_cents": 4900, "credits": 1, "grants_white_label": False},
    "deep": {"name": "Deep Audit", "amount_cents": 7900, "credits": 1, "grants_white_label": False},
}

# Bundle packs: one-off purchase, credits vary by pack. Legendary also
# unlocks white-label as a one-time perk of the bundle (separate from the
# recurring white-label subscription below).
BUNDLE_PACKS: dict[str, dict[str, Any]] = {
    "starter": {"name": "Starter Pack", "amount_cents": 9900, "credits": 3, "grants_white_label": False},
    "growth": {"name": "Growth Pack", "amount_cents": 27900, "credits": 10, "grants_white_label": False},
    "legendary": {"name": "Legendary Pack", "amount_cents": 59900, "credits": 25, "grants_white_label": True},
}

# White label add-on: recurring monthly subscription, no credits attached.
WHITE_LABEL_ADDON: dict[str, Any] = {
    "name": "White Label Add-on",
    "amount_cents": 9900,
}


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

    if product_type == "white_label":
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": WHITE_LABEL_ADDON["amount_cents"],
                        "product_data": {"name": WHITE_LABEL_ADDON["name"]},
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }
            ],
            metadata=metadata,
            subscription_data={"metadata": metadata},
            success_url=success_url,
            cancel_url=cancel_url,
        )
    elif product_type in ("tier", "bundle"):
        product = _get_one_off_product(product_type, product_id)
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": product["amount_cents"],
                        "product_data": {"name": product["name"]},
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
    sb = get_supabase()
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


def _set_white_label_active(
    user_id: str,
    active: bool,
    customer_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
) -> None:
    sb = get_supabase()
    update: dict[str, Any] = {
        "white_label_active": active,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if customer_id is not None:
        update["stripe_customer_id"] = customer_id
    if subscription_id is not None:
        update["stripe_subscription_id"] = subscription_id

    execute_with_retry(
        lambda: sb.table("app_users").update(update).eq("id", user_id).execute(),
        op="update app_users.white_label_active",
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


def fulfill_checkout_session(event: Any) -> None:
    """Called from the Stripe webhook on checkout.session.completed.

    `event` is the full verified Stripe Event (not just the session), because
    the idempotency key is the Stripe *event* id (stripe_event_id), not the
    checkout session id. Grants credits and/or white-label access based on
    the metadata carried on the session, then records the fulfillment in
    billing_transactions.
    """
    session = event["data"]["object"]
    event_id = event["id"]

    # Stripe SDK objects (StripeObject/Session/Event) only support subscript
    # access and .to_dict() — calling .get() on them raises AttributeError
    # ("... is not a dict. Use .to_dict() to convert it."). Convert once here
    # so the rest of this function can use normal dict semantics.
    session_dict = session.to_dict() if hasattr(session, "to_dict") else dict(session)

    metadata = dict(session_dict.get("metadata") or {})
    user_id = metadata.get("user_id")
    product_type = metadata.get("product_type")
    product_id = metadata.get("product_id")

    if not user_id or not product_type:
        logger.error("Checkout session (event %s) missing user_id/product_type metadata", event_id)
        return

    sb = get_supabase()

    # Idempotency pre-check: if this Stripe event was already fulfilled, no-op.
    existing = execute_with_retry(
        lambda: sb.table("billing_transactions")
        .select("id")
        .eq("stripe_event_id", event_id)
        .maybe_single()
        .execute(),
        op="check billing_transactions idempotency",
    )
    if existing and existing.data:
        logger.info("Stripe event %s already fulfilled, skipping", event_id)
        return

    session_id = session_dict.get("id")
    amount_total = session_dict.get("amount_total")
    credits_granted = 0

    if product_type in ("tier", "bundle"):
        product = _get_one_off_product(product_type, product_id or "")
        credits_granted = product["credits"]
        _increment_credits(user_id, credits_granted)
        if product["grants_white_label"]:
            _set_white_label_active(user_id, True)
    elif product_type == "white_label":
        customer_id = _extract_id(session_dict.get("customer"))
        subscription_id = _extract_id(session_dict.get("subscription"))
        _set_white_label_active(user_id, True, customer_id=customer_id, subscription_id=subscription_id)
    else:
        logger.error("Unknown product type in checkout session metadata: %s", product_type)
        return

    try:
        execute_with_retry(
            lambda: sb.table("billing_transactions")
            .insert(
                {
                    "user_id": user_id,
                    "stripe_event_id": event_id,
                    "stripe_session_id": session_id,
                    "product_type": product_type,
                    "product_id": product_id,
                    "amount_cents": amount_total,
                    "credits_granted": credits_granted,
                }
            )
            .execute(),
            op="insert billing_transactions",
        )
    except Exception as exc:  # noqa: BLE001
        # Unique-violation on stripe_event_id means a concurrent duplicate
        # delivery already recorded this event; the grant above may have
        # been double-applied in that rare race, but we must not raise here
        # (Stripe would otherwise retry indefinitely on a 5xx).
        msg = str(exc).lower()
        if "duplicate key" in msg or "23505" in msg or "unique" in msg:
            logger.warning("billing_transactions insert for event %s hit unique violation (race), ignoring", event_id)
        else:
            raise


def revoke_white_label_for_subscription(subscription: Any) -> None:
    """Called from the Stripe webhook on customer.subscription.deleted, so a
    cancelled white-label subscription turns the flag back off."""
    subscription_id = _extract_id(subscription)
    sb = get_supabase()

    result = execute_with_retry(
        lambda: sb.table("app_users")
        .select("id")
        .eq("stripe_subscription_id", subscription_id)
        .limit(1)
        .execute(),
        op="lookup app_users by stripe_subscription_id",
    )
    rows = result.data or []
    if not rows:
        return

    _set_white_label_active(rows[0]["id"], False)
