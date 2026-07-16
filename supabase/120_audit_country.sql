-- =============================================================
-- Migration 120: Country-based audits
-- =============================================================
-- Adds an optional country on an audit. When set, the worker
-- localises LLM prompts (a location hint) and passes gl/hl to the
-- SerpAPI/search calls (organic rankings, directory + site-index
-- checks) so results reflect that country. Nullable — existing
-- audits and audits with no country behave exactly as before.

ALTER TABLE geo_audits
ADD COLUMN IF NOT EXISTS country TEXT;
