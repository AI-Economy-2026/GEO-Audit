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
