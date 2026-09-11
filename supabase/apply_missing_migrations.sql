-- =============================================================
-- COMBINED: Missing migrations 230, 250, 260, 270, 280
-- Run this in the Supabase Dashboard → SQL Editor → New query
-- =============================================================

-- =============================================================
-- Migration 230: GA4 connections
-- =============================================================

CREATE TABLE IF NOT EXISTS ga4_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  google_account_email TEXT,
  refresh_token_enc TEXT NOT NULL,
  access_token_enc TEXT,
  token_expires_at TIMESTAMPTZ,
  selected_property TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_ga4_connections_user ON ga4_connections (user_id);

ALTER TABLE ga4_connections ENABLE ROW LEVEL SECURITY;

-- Tokens are never exposed to the browser session; service role only for writes.
CREATE POLICY "Users can view own ga4 connection metadata" ON ga4_connections
  FOR SELECT USING (user_id = auth.uid() OR public.is_admin());

-- =============================================================
-- Migration 250: Agency integrations (Notion, Asana, Slack, GHL, GSC, GA4)
-- =============================================================

CREATE TABLE IF NOT EXISTS agency_integrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  service TEXT NOT NULL CHECK (service IN ('notion', 'asana', 'slack', 'ghl', 'gsc', 'ga4')),
  -- Encrypted API key/token (AES-256-GCM encrypted with TOKEN_ENCRYPTION_KEY)
  credential_enc TEXT NOT NULL,
  -- Connection status
  status TEXT NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'error', 'disconnected')),
  -- Human-readable error message if status = 'error'
  last_error TEXT,
  -- Service-specific config (workspace_id, database_id, channel_id, etc.)
  -- JSONB so each service stores what it needs without schema changes
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  -- Display name for the connected account (e.g. "acme@company.com")
  display_name TEXT,
  -- Delivery tracking (like webhooks)
  send_count INTEGER NOT NULL DEFAULT 0,
  fail_count INTEGER NOT NULL DEFAULT 0,
  last_send_status INTEGER,
  last_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  -- One integration per service per agency
  UNIQUE (user_id, service)
);

CREATE INDEX IF NOT EXISTS idx_agency_integrations_user_id ON agency_integrations (user_id);
CREATE INDEX IF NOT EXISTS idx_agency_integrations_service ON agency_integrations (service);

CREATE TABLE IF NOT EXISTS agency_integration_deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  integration_id UUID NOT NULL REFERENCES agency_integrations(id) ON DELETE CASCADE,
  audit_id UUID REFERENCES geo_audits(id) ON DELETE CASCADE,
  event TEXT NOT NULL,
  -- What was sent (summary, not full payload — could be large)
  payload_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  status_code INTEGER,
  success BOOLEAN NOT NULL DEFAULT FALSE,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agency_integration_deliveries_integration_id
  ON agency_integration_deliveries (integration_id, created_at DESC);

ALTER TABLE agency_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE agency_integration_deliveries ENABLE ROW LEVEL SECURITY;

-- Users can manage their own integrations (or admins can see all)
CREATE POLICY "Users manage own integrations" ON agency_integrations
  FOR ALL USING (user_id = auth.uid() OR public.is_admin())
  WITH CHECK (user_id = auth.uid());

-- Users can view deliveries for their own integrations
CREATE POLICY "Users view own integration deliveries" ON agency_integration_deliveries
  FOR SELECT USING (
    integration_id IN (SELECT id FROM agency_integrations WHERE user_id = auth.uid())
    OR public.is_admin()
  );

-- =============================================================
-- Migration 260: Products & Services Chips
-- =============================================================

-- geo_clients.services already exists (migration 020, line 10); only
-- add the products array here.
ALTER TABLE geo_clients
ADD COLUMN IF NOT EXISTS products TEXT[] NOT NULL DEFAULT '{}';

-- geo_audits gets a products array so the audit wizard can persist what
-- the agency captured alongside the (already-existing) services list.
ALTER TABLE geo_audits
ADD COLUMN IF NOT EXISTS products TEXT[] NOT NULL DEFAULT '{}';

-- =============================================================
-- Migration 270: Audit costs (super-admin finance dashboard)
-- =============================================================

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

-- =============================================================
-- Migration 280: Agency MCP API keys
-- =============================================================

CREATE TABLE IF NOT EXISTS agency_mcp_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  api_key TEXT UNIQUE NOT NULL,
  label TEXT DEFAULT 'Default',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_used_at TIMESTAMPTZ,
  -- One MCP key per agency
  UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_agency_mcp_keys_user ON agency_mcp_keys (user_id);
CREATE INDEX IF NOT EXISTS idx_agency_mcp_keys_key ON agency_mcp_keys (api_key);

ALTER TABLE agency_mcp_keys ENABLE ROW LEVEL SECURITY;

-- Users can manage their own MCP keys (or admins can see all)
CREATE POLICY "Users manage own MCP keys" ON agency_mcp_keys
  FOR ALL USING (user_id = auth.uid() OR public.is_admin());
