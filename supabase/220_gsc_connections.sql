-- =============================================================
-- Migration 220: GSC connections
-- =============================================================

CREATE TABLE IF NOT EXISTS gsc_connections (
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

CREATE INDEX IF NOT EXISTS idx_gsc_connections_user ON gsc_connections (user_id);

ALTER TABLE gsc_connections ENABLE ROW LEVEL SECURITY;

-- Tokens are never exposed to the browser session; service role only for writes.
CREATE POLICY "Users can view own gsc connection metadata" ON gsc_connections
  FOR SELECT USING (user_id = auth.uid() OR public.is_admin());
