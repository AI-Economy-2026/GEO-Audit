-- =============================================================
-- Migration 070: Persist full citation URLs from LLM responses
-- =============================================================
-- The engine already parses every URL cited in each LLM response
-- (parse_citations in geo_audit_engine.py), but only the boolean
-- "was the brand's URL cited" was being stored. The full list was
-- thrown away.
--
-- This migration adds a citations TEXT[] column so the worker can
-- persist every cited URL per result row. The dashboard then
-- aggregates these into a "top cited domains" view per audit.

ALTER TABLE geo_audit_results
ADD COLUMN IF NOT EXISTS citations TEXT[] NOT NULL DEFAULT '{}';

-- GIN index so we can query "rows that cited domain X" cheaply
-- (used by per-domain drill-down on the sources page).
CREATE INDEX IF NOT EXISTS idx_results_citations_gin
  ON geo_audit_results USING GIN (citations);
