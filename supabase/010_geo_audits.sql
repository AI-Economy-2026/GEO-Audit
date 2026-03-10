-- =============================================================
-- Migration 010: GEO Audit tables (standalone, no org dependency)
-- =============================================================

CREATE TABLE IF NOT EXISTS geo_audits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_by UUID NOT NULL REFERENCES auth.users(id),
  brand_name TEXT NOT NULL,
  brand_url TEXT NOT NULL,
  competitors TEXT[] NOT NULL DEFAULT '{}',
  engines TEXT[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
  progress_current INTEGER DEFAULT 0,
  progress_total INTEGER DEFAULT 0,
  progress_message TEXT,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  duration_seconds INTEGER,
  dashboard_url TEXT,
  summary_json JSONB,
  visibility_rate NUMERIC(5,1),
  total_queries INTEGER,
  total_mentioned INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS geo_audit_prompts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id UUID NOT NULL REFERENCES geo_audits(id) ON DELETE CASCADE,
  prompt_id INTEGER NOT NULL,
  category TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS geo_audit_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id UUID NOT NULL REFERENCES geo_audits(id) ON DELETE CASCADE,
  prompt_id INTEGER NOT NULL,
  category TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  engine TEXT NOT NULL,
  engine_display TEXT NOT NULL,
  brand_mentioned BOOLEAN DEFAULT FALSE,
  position_rank INTEGER,
  url_cited BOOLEAN DEFAULT FALSE,
  competitor_mentions TEXT[] DEFAULT '{}',
  sentiment TEXT DEFAULT 'neutral'
    CHECK (sentiment IN ('positive', 'neutral', 'negative')),
  response_text TEXT,
  queried_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_audits_user ON geo_audits(created_by);
CREATE INDEX IF NOT EXISTS idx_geo_audits_status ON geo_audits(status);
CREATE INDEX IF NOT EXISTS idx_geo_audits_created ON geo_audits(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_geo_audit_results_audit ON geo_audit_results(audit_id);
CREATE INDEX IF NOT EXISTS idx_geo_audit_prompts_audit ON geo_audit_prompts(audit_id);

ALTER TABLE geo_audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE geo_audit_prompts ENABLE ROW LEVEL SECURITY;
ALTER TABLE geo_audit_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own audits" ON geo_audits
  FOR SELECT USING (created_by = auth.uid());

CREATE POLICY "Users can create audits" ON geo_audits
  FOR INSERT WITH CHECK (created_by = auth.uid());

CREATE POLICY "Users can view own audit prompts" ON geo_audit_prompts
  FOR SELECT USING (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

CREATE POLICY "Users can insert own audit prompts" ON geo_audit_prompts
  FOR INSERT WITH CHECK (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

CREATE POLICY "Users can view own audit results" ON geo_audit_results
  FOR SELECT USING (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

ALTER PUBLICATION supabase_realtime ADD TABLE geo_audits;
