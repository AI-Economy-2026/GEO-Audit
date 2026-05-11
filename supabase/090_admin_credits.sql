-- =============================================================
-- Migration 090: Admin role + per-agency credit system
-- =============================================================
-- Adds app_users (1:1 with auth.users) carrying role, credits,
-- agency name and status. Used to:
--   1. Distinguish admins from agencies at login time
--   2. Gate audit starts by credit balance
--   3. Let admins manage agencies from /admin
--
-- Security model:
--   - Users can only read their own app_users row (RLS).
--   - Credits / role / status are NEVER user-writable from the client
--     (no UPDATE policy). All mutations go through API endpoints with
--     the service role key.
--   - Admin operations bypass RLS via service role.
--
-- A trigger backfills future auth.users → app_users; existing users
-- are backfilled in this migration.

CREATE TABLE IF NOT EXISTS app_users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('admin', 'agency')) DEFAULT 'agency',
  agency_name TEXT,
  contact_name TEXT,
  email TEXT,
  credits_remaining INTEGER NOT NULL DEFAULT 0 CHECK (credits_remaining >= 0),
  credits_used INTEGER NOT NULL DEFAULT 0 CHECK (credits_used >= 0),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_users_role ON app_users (role);
CREATE INDEX IF NOT EXISTS idx_app_users_email ON app_users (email);

-- Auto-create profile when a new auth.users row is inserted
-- (e.g. via Supabase admin invite). SECURITY DEFINER so the trigger
-- can write into app_users regardless of caller's RLS context.
CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.app_users (id, role, email)
  VALUES (NEW.id, 'agency', NEW.email)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user();

-- Backfill any existing auth users that don't have a profile yet
INSERT INTO app_users (id, role, email)
SELECT id, 'agency', email FROM auth.users
ON CONFLICT (id) DO NOTHING;

-- RLS — users can read their own row only. NO update / insert / delete
-- policy on purpose: any mutation has to come from a service-role API.
ALTER TABLE app_users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can read own profile" ON app_users;
CREATE POLICY "Users can read own profile" ON app_users
  FOR SELECT USING (id = auth.uid());
