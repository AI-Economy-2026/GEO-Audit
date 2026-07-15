-- =============================================================
-- Migration 110: Admins can read every agency's audit data
-- =============================================================
-- The admin panel links through to an audit's report / workspace
-- dashboard. Those pages read via the browser (RLS) client, so
-- without an admin read policy an admin sees "not found" for any
-- audit they didn't create.
--
-- This adds SELECT policies letting role='admin' users read all
-- audits, prompts, results, action items and clients. Mutations
-- still go only through service-role API routes.

-- helper: is the current user an admin?
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.app_users
    WHERE id = auth.uid() AND role = 'admin'
  );
$$;

DROP POLICY IF EXISTS "Admins view all audits" ON geo_audits;
CREATE POLICY "Admins view all audits" ON geo_audits
  FOR SELECT USING (public.is_admin());

DROP POLICY IF EXISTS "Admins view all audit prompts" ON geo_audit_prompts;
CREATE POLICY "Admins view all audit prompts" ON geo_audit_prompts
  FOR SELECT USING (public.is_admin());

DROP POLICY IF EXISTS "Admins view all audit results" ON geo_audit_results;
CREATE POLICY "Admins view all audit results" ON geo_audit_results
  FOR SELECT USING (public.is_admin());

DROP POLICY IF EXISTS "Admins view all clients" ON geo_clients;
CREATE POLICY "Admins view all clients" ON geo_clients
  FOR SELECT USING (public.is_admin());

DROP POLICY IF EXISTS "Admins view all action items" ON geo_audit_action_items;
CREATE POLICY "Admins view all action items" ON geo_audit_action_items
  FOR SELECT USING (public.is_admin());
