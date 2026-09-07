-- =============================================================
-- Migration 180: Billing integrity
-- =============================================================
-- Two fixes, both about not losing or giving away money.
--
-- 1. billing_transactions.product_type has to be able to record a session
--    we could NOT fulfil. Both dead ends in fulfill_checkout_session hand
--    Stripe a 2xx, so Stripe marks the event delivered and never mentions
--    it again; without a row the money is taken and nothing anywhere can
--    find it. 'white_label' stays in the list so existing rows remain
--    valid, even though nothing writes it any more.
--
-- 2. Credits were moved with a read-modify-write across a network call, in
--    three places: the webhook grant, the audit-creation spend and the
--    re-audit spend. Two of those racing lose one of the writes. The worst
--    case is a customer paying, the grant landing, and a concurrent audit
--    creation writing back a balance it read before the grant, which erases
--    the purchase. These two functions make each move atomic in one
--    statement, so the loser of a race still applies.

-- ---------- 1. allow the unfulfillable marker ----------
ALTER TABLE billing_transactions
  DROP CONSTRAINT IF EXISTS billing_transactions_product_type_check;

ALTER TABLE billing_transactions
  ADD CONSTRAINT billing_transactions_product_type_check
  CHECK (product_type IN ('tier', 'bundle', 'white_label', 'unfulfillable'));

-- ---------- 2. atomic credit movement ----------

-- Grant: add n credits in one statement. Returns the new balance.
CREATE OR REPLACE FUNCTION public.grant_credits(p_user_id UUID, p_credits INTEGER)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_new INTEGER;
BEGIN
  IF p_credits IS NULL OR p_credits <= 0 THEN
    RAISE EXCEPTION 'grant_credits: p_credits must be positive, got %', p_credits;
  END IF;

  UPDATE app_users
     SET credits_remaining = credits_remaining + p_credits,
         updated_at        = now()
   WHERE id = p_user_id
  RETURNING credits_remaining INTO v_new;

  IF v_new IS NULL THEN
    RAISE EXCEPTION 'grant_credits: no app_users row for %', p_user_id;
  END IF;

  RETURN v_new;
END;
$$;

-- Spend: take one credit only if there is one, in the same statement that
-- checks. Returns the new balance, or NULL when the caller had none, so the
-- caller can refuse without a separate read that another writer can outrun.
CREATE OR REPLACE FUNCTION public.spend_credit(p_user_id UUID)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_new INTEGER;
BEGIN
  UPDATE app_users
     SET credits_remaining = credits_remaining - 1,
         credits_used      = credits_used + 1,
         updated_at        = now()
   WHERE id = p_user_id
     AND credits_remaining > 0
  RETURNING credits_remaining INTO v_new;

  RETURN v_new;  -- NULL when nothing was updated, i.e. no credits left
END;
$$;

-- Only the service role calls these; no anon or authenticated grant.
REVOKE ALL ON FUNCTION public.grant_credits(UUID, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.spend_credit(UUID) FROM PUBLIC;
