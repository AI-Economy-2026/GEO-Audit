-- =============================================================
-- Migration 130: Client industry
-- =============================================================
-- Adds an optional industry/vertical label on a client, shown on
-- the redesigned /clients table. Nullable — existing clients and
-- clients with no industry set behave exactly as before.

ALTER TABLE geo_clients
ADD COLUMN IF NOT EXISTS industry TEXT;
