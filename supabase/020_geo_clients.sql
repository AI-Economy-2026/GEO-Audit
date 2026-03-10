CREATE TABLE IF NOT EXISTS geo_clients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_by UUID NOT NULL REFERENCES auth.users(id),
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  intake_token TEXT UNIQUE NOT NULL,
  report_slug TEXT UNIQUE NOT NULL,
  email TEXT,
  competitors TEXT[] NOT NULL DEFAULT '{}',
  services TEXT[] NOT NULL DEFAULT '{}',
  industry TEXT,
  location TEXT,
  intake_completed_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'pending_intake'
    CHECK (status IN ('pending_intake', 'intake_completed', 'auditing', 'completed', 'failed')),
  audit_id UUID REFERENCES geo_audits(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_clients_user ON geo_clients(created_by);
CREATE INDEX IF NOT EXISTS idx_geo_clients_token ON geo_clients(intake_token);
CREATE INDEX IF NOT EXISTS idx_geo_clients_slug ON geo_clients(report_slug);

ALTER TABLE geo_clients ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own clients" ON geo_clients
  FOR SELECT USING (created_by = auth.uid());

CREATE POLICY "Users can create clients" ON geo_clients
  FOR INSERT WITH CHECK (created_by = auth.uid());

CREATE POLICY "Users can update own clients" ON geo_clients
  FOR UPDATE USING (created_by = auth.uid());

CREATE POLICY "Public can view audits linked to clients" ON geo_audits
  FOR SELECT USING (
    id IN (SELECT audit_id FROM geo_clients WHERE audit_id IS NOT NULL)
  );

CREATE OR REPLACE FUNCTION sync_client_audit_status()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.status IN ('completed', 'failed') AND OLD.status NOT IN ('completed', 'failed') THEN
    UPDATE geo_clients
    SET status = NEW.status,
        updated_at = NOW()
    WHERE audit_id = NEW.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_client_audit_status
AFTER UPDATE ON geo_audits
FOR EACH ROW
EXECUTE FUNCTION sync_client_audit_status();

ALTER PUBLICATION supabase_realtime ADD TABLE geo_clients;
