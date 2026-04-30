-- =============================================================
-- Migration 060: 90-Day Action Plan
-- =============================================================
-- Adds geo_audit_action_items, generated once per audit by Claude
-- on the first /activate visit. Items are completable with a
-- timestamp so the agency can track progress over time.

CREATE TABLE IF NOT EXISTS geo_audit_action_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id UUID NOT NULL REFERENCES geo_audits(id) ON DELETE CASCADE,
  week_number INTEGER NOT NULL CHECK (week_number BETWEEN 1 AND 13),
  category TEXT NOT NULL CHECK (category IN ('technical', 'non_technical')),
  title TEXT NOT NULL,
  description TEXT,
  effort_label TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_action_items_audit
  ON geo_audit_action_items (audit_id, week_number, sort_order);

CREATE INDEX IF NOT EXISTS idx_action_items_audit_category
  ON geo_audit_action_items (audit_id, category);

ALTER TABLE geo_audit_action_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own audit action items" ON geo_audit_action_items
  FOR SELECT USING (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

CREATE POLICY "Users can insert own audit action items" ON geo_audit_action_items
  FOR INSERT WITH CHECK (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

CREATE POLICY "Users can update own audit action items" ON geo_audit_action_items
  FOR UPDATE USING (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

CREATE POLICY "Users can delete own audit action items" ON geo_audit_action_items
  FOR DELETE USING (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );
