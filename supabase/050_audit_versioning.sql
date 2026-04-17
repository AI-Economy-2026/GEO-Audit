-- =============================================================
-- Migration 050: Audit Versioning (Re-Audit Support)
-- =============================================================
-- Adds parent_audit_id and version columns to geo_audits so
-- re-audits can be linked to their originals and scored over time.

-- Self-referencing FK: NULL means this is the first audit (version 1).
ALTER TABLE geo_audits
ADD COLUMN IF NOT EXISTS parent_audit_id UUID REFERENCES geo_audits(id),
ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

-- Fast lookup: all versions of a given root audit
CREATE INDEX IF NOT EXISTS idx_geo_audits_parent ON geo_audits(parent_audit_id);

-- Allow users to update their own audits (needed for re-audit status writes)
CREATE POLICY "Users can update own audits" ON geo_audits
  FOR UPDATE USING (created_by = auth.uid());
