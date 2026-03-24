-- =============================================================
-- Migration 040: Wizard Fields & Prompt Types
-- =============================================================

-- Add new fields to geo_audits
ALTER TABLE geo_audits
ADD COLUMN IF NOT EXISTS user_name TEXT,
ADD COLUMN IF NOT EXISTS user_email TEXT,
ADD COLUMN IF NOT EXISTS keywords TEXT[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ;

-- Add prompt_type to geo_audit_prompts to differentiate Intent vs Ranking
ALTER TABLE geo_audit_prompts
ADD COLUMN IF NOT EXISTS prompt_type TEXT DEFAULT 'ranking' 
CHECK (prompt_type IN ('intent', 'ranking'));

-- Add prompt_type to geo_audit_results
ALTER TABLE geo_audit_results
ADD COLUMN IF NOT EXISTS prompt_type TEXT DEFAULT 'ranking' 
CHECK (prompt_type IN ('intent', 'ranking'));
