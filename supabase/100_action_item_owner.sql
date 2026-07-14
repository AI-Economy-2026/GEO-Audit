-- =============================================================
-- Migration 100: Assign action items to an owner
-- =============================================================
-- Adds a free-text owner column to geo_audit_action_items so each
-- 90-day plan item can be assigned to a person on the /activate
-- page. Nullable — items are unassigned by default.

ALTER TABLE geo_audit_action_items
ADD COLUMN IF NOT EXISTS owner TEXT;
