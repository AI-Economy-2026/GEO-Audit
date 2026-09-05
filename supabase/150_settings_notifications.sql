-- =============================================================
-- Migration 150: Settings notifications
-- =============================================================
-- Adds the column needed to back the "Email notifications" toggle
-- on the new Account Settings page:
--   - notifications_enabled: whether the agency wants to receive
--     email notifications (audit complete, credit top-ups, etc.).
-- Nullable-safe / default true — existing rows keep notifications on.

ALTER TABLE app_users
ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN NOT NULL DEFAULT true;
