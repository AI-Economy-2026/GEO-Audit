-- =============================================================
-- Bootstrap seeder — first RankCo admin
-- =============================================================
-- Run AFTER 090_admin_credits.sql.
--
-- Credentials seeded:
--   email:    rankcoadmin@yopmail.com
--   password: Rankco@1234
--
-- Idempotent — safe to run multiple times; existing user is upgraded
-- to role='admin' if they already exist.

DO $$
DECLARE
  admin_email TEXT := 'rankcoadmin@yopmail.com';
  admin_password TEXT := 'Rankco@1234';
  admin_id UUID;
BEGIN
  -- 1. Look for an existing auth user with this email
  SELECT id INTO admin_id FROM auth.users WHERE email = admin_email LIMIT 1;

  IF admin_id IS NULL THEN
    admin_id := gen_random_uuid();

    -- Insert into auth.users with a bcrypt'd password
    INSERT INTO auth.users (
      instance_id,
      id,
      aud,
      role,
      email,
      encrypted_password,
      email_confirmed_at,
      raw_app_meta_data,
      raw_user_meta_data,
      created_at,
      updated_at,
      confirmation_token,
      email_change,
      email_change_token_new,
      recovery_token
    )
    VALUES (
      '00000000-0000-0000-0000-000000000000',
      admin_id,
      'authenticated',
      'authenticated',
      admin_email,
      crypt(admin_password, gen_salt('bf')),
      NOW(),
      '{"provider":"email","providers":["email"]}'::jsonb,
      '{}'::jsonb,
      NOW(),
      NOW(),
      '',
      '',
      '',
      ''
    );

    -- Matching identity row so Supabase password auth resolves the user
    INSERT INTO auth.identities (
      id,
      user_id,
      identity_data,
      provider,
      provider_id,
      last_sign_in_at,
      created_at,
      updated_at
    )
    VALUES (
      gen_random_uuid(),
      admin_id,
      jsonb_build_object('sub', admin_id::text, 'email', admin_email),
      'email',
      admin_id::text,
      NOW(),
      NOW(),
      NOW()
    );
  END IF;

  -- 2. Upsert app_users profile with role='admin' and unlimited-feel credits
  INSERT INTO public.app_users (id, role, email, agency_name, credits_remaining)
  VALUES (admin_id, 'admin', admin_email, 'RankCo Admin', 0)
  ON CONFLICT (id) DO UPDATE
    SET role = 'admin',
        agency_name = COALESCE(app_users.agency_name, 'RankCo Admin'),
        updated_at = NOW();
END $$;

-- Verify
SELECT id, email, role, agency_name FROM public.app_users WHERE email = 'rankcoadmin@yopmail.com';
