-- 270_audit_costs.sql
-- Per-audit API cost tracking for the super-admin finance dashboard.
-- Each row records the external API usage of a single audit run and the
-- computed cost in cents so the admin can see revenue vs cost per agency.

CREATE TABLE IF NOT EXISTS audit_costs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id UUID REFERENCES geo_audits(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  serpapi_calls INTEGER NOT NULL DEFAULT 0,
  dataforseo_calls INTEGER NOT NULL DEFAULT 0,
  ai_input_tokens INTEGER NOT NULL DEFAULT 0,
  ai_output_tokens INTEGER NOT NULL DEFAULT 0,
  ai_model TEXT,
  backlinks_calls INTEGER NOT NULL DEFAULT 0,
  pages_crawled INTEGER NOT NULL DEFAULT 0,
  cost_cents INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_costs_user ON audit_costs (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_costs_created ON audit_costs (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_costs_audit ON audit_costs (audit_id);

ALTER TABLE audit_costs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins can view audit costs" ON audit_costs
  FOR SELECT USING (public.is_admin());

-- Fix the billing_transactions product_type constraint to include 'addon'
-- (SEO add-on purchases write product_type='addon' but the constraint
-- only allowed tier/bundle/white_label/unfulfillable).
ALTER TABLE billing_transactions
  DROP CONSTRAINT IF EXISTS billing_transactions_product_type_check;
ALTER TABLE billing_transactions
  ADD CONSTRAINT billing_transactions_product_type_check
  CHECK (product_type IN ('tier', 'bundle', 'white_label', 'addon', 'unfulfillable'));
