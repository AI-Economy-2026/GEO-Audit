-- =============================================================
-- Migration 210: Watch tracking
-- =============================================================

CREATE TABLE IF NOT EXISTS geo_watches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id UUID NOT NULL REFERENCES geo_audits(id) ON DELETE CASCADE,
  created_by UUID NOT NULL REFERENCES app_users(id),
  cadence TEXT NOT NULL DEFAULT 'monthly'
    CHECK (cadence IN ('weekly', 'biweekly', 'monthly')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'paused', 'cancelled')),
  next_run_at TIMESTAMPTZ NOT NULL,
  last_run_at TIMESTAMPTZ,
  last_audit_id UUID REFERENCES geo_audits(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_watches_next_run
  ON geo_watches (status, next_run_at);

CREATE INDEX IF NOT EXISTS idx_geo_watches_user
  ON geo_watches (created_by);

ALTER TABLE geo_watches ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own watches" ON geo_watches
  FOR SELECT USING (
    created_by = auth.uid() OR public.is_admin()
  );

CREATE POLICY "Users can insert own watches" ON geo_watches
  FOR INSERT WITH CHECK (created_by = auth.uid());

CREATE POLICY "Users can update own watches" ON geo_watches
  FOR UPDATE USING (created_by = auth.uid() OR public.is_admin());
