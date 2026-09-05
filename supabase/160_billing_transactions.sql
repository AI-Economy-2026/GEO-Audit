-- =============================================================
-- Migration 160: Billing transactions
-- =============================================================
-- Ledger of fulfilled Stripe checkout events. Serves two purposes:
--   1. Idempotency guard: stripe_event_id is UNIQUE NOT NULL, so a
--      duplicate webhook delivery for the same event fails the insert
--      and fulfillment is skipped instead of double-granting credits.
--   2. Audit trail: records what was purchased, by whom, and when,
--      for support/finance/reconciliation.

CREATE TABLE IF NOT EXISTS billing_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES app_users(id),
    stripe_event_id TEXT UNIQUE NOT NULL,
    stripe_session_id TEXT,
    product_type TEXT NOT NULL CHECK (product_type IN ('tier', 'bundle', 'white_label')),
    product_id TEXT,
    amount_cents INTEGER,
    credits_granted INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_transactions_user_id
ON billing_transactions (user_id);
