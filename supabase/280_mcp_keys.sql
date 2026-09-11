-- =============================================================
-- Migration 280: Agency MCP API keys
-- Per-agency keys for authenticating MCP tool calls from Claude.
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
