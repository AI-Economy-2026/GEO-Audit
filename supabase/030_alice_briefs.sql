CREATE TABLE IF NOT EXISTS geo_alice_briefs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id UUID NOT NULL REFERENCES geo_audits(id) ON DELETE CASCADE,
  client_name TEXT NOT NULL,
  brief_json JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'in_progress', 'completed')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alice_briefs_audit ON geo_alice_briefs(audit_id);

ALTER TABLE geo_alice_briefs ENABLE ROW LEVEL SECURITY;
