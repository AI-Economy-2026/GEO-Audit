-- =============================================================
-- Migration 170: Contact form submissions
-- =============================================================
-- Durable store for the public marketing site's contact form.
-- Until now /api/contact only emailed the Gatha inbox, so a bounced,
-- spam-filtered or missed notification lost the lead permanently.
-- Every submission is now written here as well, and the email send
-- and the insert are independent (see src/app/api/contact/route.ts).
--
-- Security model:
--   - Inserts come ONLY from the public API route using the service
--     role key, so there is deliberately no INSERT policy.
--   - Only role='admin' users can read, via public.is_admin() from
--     migration 110. Agencies and anonymous visitors see nothing.
--   - handled is flipped from /api/admin/enquiries (service role).

CREATE TABLE IF NOT EXISTS contact_submissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  company TEXT,
  phone TEXT,
  topic TEXT,
  message TEXT NOT NULL,
  -- "Keep me updated" tick box on the form
  newsletter BOOLEAN NOT NULL DEFAULT false,
  -- false = still to be actioned by the team, true = dealt with
  handled BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contact_submissions_created
ON contact_submissions (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_contact_submissions_handled
ON contact_submissions (handled);

-- RLS: admins read, nobody else. No INSERT / UPDATE / DELETE policy
-- on purpose: every mutation goes through a service-role API route.
ALTER TABLE contact_submissions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Admins view all contact submissions" ON contact_submissions;
CREATE POLICY "Admins view all contact submissions" ON contact_submissions
  FOR SELECT USING (public.is_admin());
