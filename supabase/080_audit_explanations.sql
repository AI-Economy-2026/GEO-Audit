-- =============================================================
-- Migration 080: Persist Explain-this drawer content per card
-- =============================================================
-- Stores the deterministic base explanation + accumulated LLM
-- follow-up Q&A for every (audit_id, target_type, target_id) tuple
-- so re-opening the drawer shows the previous conversation instead
-- of regenerating from scratch and losing the user's chat history.

CREATE TABLE IF NOT EXISTS geo_audit_explanations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id UUID NOT NULL REFERENCES geo_audits(id) ON DELETE CASCADE,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  target_label TEXT NOT NULL,
  target_value TEXT,
  target_meta JSONB,
  base_explanation JSONB NOT NULL,
  follow_ups JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(audit_id, target_type, target_id)
);

CREATE INDEX IF NOT EXISTS idx_explanations_audit
  ON geo_audit_explanations (audit_id);

ALTER TABLE geo_audit_explanations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own audit explanations" ON geo_audit_explanations
  FOR SELECT USING (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

CREATE POLICY "Users can insert own audit explanations" ON geo_audit_explanations
  FOR INSERT WITH CHECK (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

CREATE POLICY "Users can update own audit explanations" ON geo_audit_explanations
  FOR UPDATE USING (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );
