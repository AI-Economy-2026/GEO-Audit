-- =============================================================
-- Migration 190: explicit RLS policies for geo_alice_briefs
-- =============================================================
-- 030_alice_briefs.sql runs `ALTER TABLE geo_alice_briefs ENABLE ROW LEVEL
-- SECURITY` and then defines no policies at all. Postgres reads that as deny
-- everything, so the table's access rules were an accident of omission rather
-- than a decision: the worker could still write because the service role
-- bypasses RLS, while any signed-in user reading the table got zero rows with
-- no error. That is the safe direction to fail, but it is not stated
-- anywhere, so the next person to add a read path would have found an empty
-- table and no explanation.
--
-- These policies write the intent down. They mirror the shape already used
-- for geo_audit_prompts and geo_audit_results in 010, and the admin
-- read-all pattern from 110.
--
-- Writes stay deliberately unpolicied. Only the worker creates briefs, and it
-- connects with the service role, which is not subject to RLS. Adding an
-- INSERT policy for authenticated users would widen access for no caller.

-- A user can read the briefs belonging to audits they own.
DROP POLICY IF EXISTS "Users can view own alice briefs" ON geo_alice_briefs;
CREATE POLICY "Users can view own alice briefs" ON geo_alice_briefs
  FOR SELECT USING (
    audit_id IN (SELECT id FROM geo_audits WHERE created_by = auth.uid())
  );

-- Admins can read all of them, matching "Admins view all audits" in 110.
DROP POLICY IF EXISTS "Admins view all alice briefs" ON geo_alice_briefs;
CREATE POLICY "Admins view all alice briefs" ON geo_alice_briefs
  FOR SELECT USING (public.is_admin());

-- Belt and braces: RLS must stay on. Re-asserting it makes this migration
-- safe to run against a database where someone disabled it by hand.
ALTER TABLE geo_alice_briefs ENABLE ROW LEVEL SECURITY;
