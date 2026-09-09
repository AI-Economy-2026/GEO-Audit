-- =============================================================
-- Migration 200: SEO add-on entitlements + audit flag
-- =============================================================

ALTER TABLE app_users
  ADD COLUMN IF NOT EXISTS seo_addon_credits INTEGER NOT NULL DEFAULT 0
    CHECK (seo_addon_credits >= 0);

ALTER TABLE geo_audits
  ADD COLUMN IF NOT EXISTS seo_addon_enabled BOOLEAN NOT NULL DEFAULT FALSE;

CREATE OR REPLACE FUNCTION public.grant_seo_addon(
  p_user_id UUID,
  p_credits INTEGER DEFAULT 1
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_new INTEGER;
BEGIN
  IF p_credits IS NULL OR p_credits < 1 THEN
    RAISE EXCEPTION 'grant_seo_addon: credits must be >= 1';
  END IF;
  UPDATE app_users
     SET seo_addon_credits = seo_addon_credits + p_credits,
         updated_at = NOW()
   WHERE id = p_user_id
  RETURNING seo_addon_credits INTO v_new;
  IF v_new IS NULL THEN
    RAISE EXCEPTION 'grant_seo_addon: no app_users row for %', p_user_id;
  END IF;
  RETURN v_new;
END;
$$;

CREATE OR REPLACE FUNCTION public.spend_seo_addon(
  p_user_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_new INTEGER;
BEGIN
  UPDATE app_users
     SET seo_addon_credits = seo_addon_credits - 1,
         updated_at = NOW()
   WHERE id = p_user_id
     AND seo_addon_credits > 0
  RETURNING seo_addon_credits INTO v_new;
  IF v_new IS NULL THEN
    RAISE EXCEPTION 'spend_seo_addon: insufficient seo_addon_credits for %', p_user_id;
  END IF;
  RETURN v_new;
END;
$$;

REVOKE ALL ON FUNCTION public.grant_seo_addon(UUID, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.spend_seo_addon(UUID) FROM PUBLIC;
