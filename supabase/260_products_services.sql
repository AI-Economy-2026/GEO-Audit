-- =============================================================
-- Migration 260: Products & Services Chips
-- =============================================================

-- geo_clients.services already exists (migration 020, line 10); only
-- add the products array here.
ALTER TABLE geo_clients
ADD COLUMN IF NOT EXISTS products TEXT[] NOT NULL DEFAULT '{}';

-- geo_audits gets a products array so the audit wizard can persist what
-- the agency captured alongside the (already-existing) services list.
ALTER TABLE geo_audits
ADD COLUMN IF NOT EXISTS products TEXT[] NOT NULL DEFAULT '{}';
