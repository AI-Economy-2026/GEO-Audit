-- =============================================================
-- Migration 230: Agency team members
-- =============================================================

CREATE TABLE IF NOT EXISTS agency_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agency_owner_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
  email TEXT NOT NULL,
  member_role TEXT NOT NULL DEFAULT 'member'
    CHECK (member_role IN ('owner', 'admin', 'member', 'viewer')),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'active', 'revoked')),
  invite_token TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (agency_owner_id, email)
);

CREATE INDEX IF NOT EXISTS idx_agency_members_owner ON agency_members (agency_owner_id);
CREATE INDEX IF NOT EXISTS idx_agency_members_user ON agency_members (user_id);
CREATE INDEX IF NOT EXISTS idx_agency_members_token ON agency_members (invite_token);

ALTER TABLE agency_members ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owners and members can view roster" ON agency_members
  FOR SELECT USING (
    agency_owner_id = auth.uid()
    OR user_id = auth.uid()
    OR public.is_admin()
  );
