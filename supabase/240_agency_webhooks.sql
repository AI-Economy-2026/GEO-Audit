-- =============================================================
-- Migration 240: Outbound agency webhooks
-- =============================================================

CREATE TABLE IF NOT EXISTS agency_webhooks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  secret TEXT NOT NULL,
  events TEXT[] NOT NULL DEFAULT ARRAY['audit.completed'],
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  fail_count INTEGER NOT NULL DEFAULT 0,
  last_status INTEGER,
  last_delivered_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agency_webhooks_user ON agency_webhooks (user_id);
CREATE INDEX IF NOT EXISTS idx_agency_webhooks_enabled ON agency_webhooks (enabled) WHERE enabled;

CREATE TABLE IF NOT EXISTS agency_webhook_deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  webhook_id UUID NOT NULL REFERENCES agency_webhooks(id) ON DELETE CASCADE,
  event TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  status_code INTEGER,
  success BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook
  ON agency_webhook_deliveries (webhook_id, created_at DESC);

ALTER TABLE agency_webhooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE agency_webhook_deliveries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own webhooks" ON agency_webhooks
  FOR ALL USING (user_id = auth.uid() OR public.is_admin())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "Users view own webhook deliveries" ON agency_webhook_deliveries
  FOR SELECT USING (
    webhook_id IN (SELECT id FROM agency_webhooks WHERE user_id = auth.uid())
    OR public.is_admin()
  );
