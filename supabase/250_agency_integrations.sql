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
