-- =============================================================
-- Migration 140: Stripe billing
-- =============================================================
-- Adds the columns needed to back Stripe checkout + subscription
-- fulfillment on app_users:
--   - white_label_active: set true by the white-label subscription
--     (or a Legendary bundle purchase) and back to false when the
--     subscription is cancelled.
--   - stripe_customer_id / stripe_subscription_id: track the active
--     white-label subscription so a later cancellation webhook can
--     look up which agency to revoke it for.
-- Nullable / default false — existing rows behave exactly as before.

ALTER TABLE app_users
ADD COLUMN IF NOT EXISTS white_label_active BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE app_users
ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;

ALTER TABLE app_users
ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;

CREATE INDEX IF NOT EXISTS idx_app_users_stripe_subscription_id
ON app_users (stripe_subscription_id);
