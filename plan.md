# Gatha - Project Plan

> Consolidated from the five handover docs in `todos/`:
> Code Review Report, Hosting & Infrastructure, Outbound Emails,
> Payments & Billing, Technical Setup.
> Verified against repos `GEO-Audit` (engine) @ `c99c001` and
> `GEO-Audit-Files` (web app) @ `8b3c8d6`, branch `fix/security-audit-phase1`.

---

## 1. What the platform is

Gatha is a GEO (Generative Engine Optimization) visibility audit SaaS.

- **Agency** logs in, completes a wizard, or sends a client an intake link.
- A row is written to `geo_audits` and `geo_audit_prompts`, one credit is spent.
- The web app calls the **audit engine** (FastAPI worker) at `GEO_WORKER_URL`
  with a bearer token (`GEO_WORKER_API_KEY` == engine's `WORKER_API_KEY`).
- The engine queries each selected AI engine per prompt (all routed through
  **OpenRouter**), analyses mentions/citations/sentiment, writes
  `geo_audit_results`, computes the summary, generates a branded HTML report,
  uploads it to Supabase Storage, and marks the audit completed.
- The UI reads results live.

### Repos & runtime

| Piece | Repo | Tech | Runs on |
|---|---|---|---|
| Web app, public site, API routes | `GEO-Audit-Files` (app2) | Next.js 16.1.6, React 19.2.3 | Node host (Hostinger) |
| Audit engine | `GEO-Audit` (app1) | Python 3.12, FastAPI, uvicorn | Railway, Dockerfile, port 8080 |
| Database, auth, storage | — | Supabase (Postgres + Auth + Storage) | Supabase cloud |

---

## 2. Security posture (already in place)

- Auth via Supabase; every request verified against their auth server, not the browser.
- RLS enabled on all tables. Admin access verified against the DB, not the login token.
- Passwords never handled by us. Sessions in secure server-side cookies.
- All pages require login except public marketing pages.
- No raw SQL anywhere -> no SQL injection surface.
- Supabase service key is server-side only.
- Card details never touch Gatha; Stripe hosted checkout only.
- Stripe webhooks are signature-verified.
- Audit engine endpoints require API key, compared in a timing-safe way.
- Security headers enforced (CSP, HSTS, clickjacking, referrer).

---

## 3. Accounts to move into the client's name

Send credentials out-of-band; rotate anything shared during development once the client has their own access.

| Account | Controls | Risk if left with us |
|---|---|---|
| GoDaddy | Domain + DNS (gatha.ai, staging subdomain) | Site and email can be redirected |
| Hostinger | Staging, live, audit engine | Nothing runs without it |
| Supabase | All customer data, logins, reports | The entire database |
| OpenRouter | All six AI engines | Audits stop when credit runs out |
| Stripe | Customer payments | Already the client's |
| Resend | All outgoing email | Password resets and invites stop |
| SerpAPI | Search lookups | Part of each audit fails |
| GitHub | Both code repos | Already the client's |

---

## 4. AI engine access (OpenRouter)

All six audit engines route through one `OPENROUTER_API_KEY`. Top up OpenRouter and all six keep running; let it run dry and all six stop at once.

| Engine | OpenRouter model |
|---|---|
| ChatGPT | `openai/gpt-5.1` |
| Claude | `anthropic/claude-opus-5` |
| Gemini | `google/gemini-3.1-pro-preview` |
| Perplexity | `perplexity/sonar-pro` |
| Grok | `x-ai/grok-4.6` |
| DeepSeek | `deepseek/deepseek-v4-pro` |

Two AI costs sit outside OpenRouter:
- **OpenAI** directly (`OPENAI_API_KEY`) - prompt generation, gpt-4o-mini analysis + sentiment scoring.
- **SerpAPI** (`SERPAPI_API_KEY`) - search result lookups.

Old per-engine keys (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `PERPLEXITY_API_KEY`,
`XAI_API_KEY`, `DEEPSEEK_API_KEY`, `META_LLAMA_API_KEY`) are no longer used and can be unset.

---

## 5. Environment variables

### Web app (app2 / `GEO-Audit-Files/.env.local`)

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SITE_URL` | Public origin. Canonicals, social images, sitemap, every emailed link. Set at build time. |
| `SITE_URL` | Runtime override for the same value, no rebuild needed |
| `NEXT_PUBLIC_ALLOW_INDEXING` | `true` on production only |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (browser) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public Supabase key (browser-safe) |
| `SUPABASE_SERVICE_ROLE_KEY` | Full DB access. Server only |
| `GEO_WORKER_URL` | Where the engine is reachable |
| `GEO_WORKER_API_KEY` | Shared secret, must match engine's `WORKER_API_KEY` |
| `ANTHROPIC_API_KEY` | Report generation and prompt extraction |
| `RESEND_API_KEY` / `RESEND_FROM` | Password resets, invites, From address |
| `CONTACT_INBOX` | Where contact form submissions are emailed |

### Audit engine (app1 / `GEO-Audit/.env`)

| Variable | Purpose |
|---|---|
| `WORKER_API_KEY` | Secret the web app must present |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | DB access for writing results |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Checkout sessions + webhook verification |
| `STRIPE_TAX_CODE` | Product tax code, default `txcd_10000000` |
| `OPENROUTER_API_KEY` | All model calls (every audited engine) |
| `SERPAPI_API_KEY` | Search result lookups |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASS` `SMTP_FROM` | Engine-side email (legacy - see section 7) |

---

## 6. Payments & billing

Stripe hosted checkout. Currently on sandbox keys; one test purchase confirmed.

**To go live:** set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` to live values on the engine, and point the Stripe webhook endpoint at it. Until the webhook secret is correct, payments succeed but no credits are granted.

### Products (USD)

| Product | ID | Price | Credits granted |
|---|---|---|---|
| Snapshot Audit | `snapshot` | $19 | 1 |
| Standard Audit | `standard` | $49 | 1 |
| Deep Audit | `deep` | $79 | 1 |
| Starter Pack | `starter` | $99 | 3 |
| Growth Pack | `growth` | $279 | 10 |
| Legendary Pack | `legendary` | $599 | 25 |

### Known issue - needs a decision
The three one-off prices all grant **one credit** and run an identical audit (same 30 prompts, same six engines). The designs specified per-tier limits (25/50/100 prompts, 3/5/5 engines) that were never built, so **$79 currently buys what $19 buys**. Flagged, not shipped silently - needs a decision either way.

Credits do not reset monthly. Bundle credits last 12 months from purchase.

### Tax
Stripe Tax is on. Tax is added on top of the listed price at checkout.
- $19 audit -> $20.90 for an Australian buyer (GST 10%)
- $19 audit -> $22.42 for an Indian buyer
Matches the pricing page footer. Every line item needs a product tax code or checkout is rejected (defaults to `txcd_10000000`, overridable via `STRIPE_TAX_CODE`).

### How a purchase becomes credits
Credits are added **only after** the ledger row is written, and that row is unique on the Stripe event ID. Stripe retries webhooks, so this prevents one payment granting credits twice. A payment that can't be matched to a customer or product is still recorded as `unfulfillable` so money-taken-not-delivered is findable.

### Webhook events handled

| Event | What happens |
|---|---|
| `checkout.session.completed` | Credits granted, ledger row written |
| `checkout.session.async_payment_succeeded` | Same, for slower payment methods |
| `checkout.session.async_payment_failed` | Recorded, no credits granted |
| `charge.refunded` | Logged for manual action |
| `charge.dispute.created` | Logged for manual action |

Refunds and disputes are deliberately manual - they do not auto-revoke credits. If a customer already spent them, reversing the balance is a judgement call, so the event is logged loudly and left to a person.

---

## 7. Outbound emails

Two senders in use:
- **Resend** - sends everything from the web app. This is the live path.
- **SMTP** - sends one email from the audit engine. Legacy duplicate (see below).

### Automated emails
1. **Agency welcome / invite** - no self-signup; this is how every agency gets in. Contains the temporary password in the body. Password is never stored in plaintext, so it cannot be looked up later. An admin can re-send the invite, which generates a new temporary password (original cannot be recovered).
2. **Password reset** - Supabase's own email templates are NOT used. The app generates the recovery link itself and sends it through Resend, so configuring SMTP inside Supabase has no effect on it.
3. **Contact form notification** - the one email that comes IN to the client. The submission is also saved to the DB and listed at `/admin/enquiries`, so nothing is lost if the email fails.

### Not automated emails (open the visitor's own client)
- Client intake link: on "New client", the agency's browser opens a pre-filled `mailto:` draft. The agency sends it from their own address. This is why intake invites appear to come from the agency, not Gatha.
- Every "get in touch" button (reports, pricing, sidebar, buy credits modal) is a `mailto:hello@gatha.ai` link.
- Sending intake invites from the platform instead of a `mailto:` draft is a known follow-up, not built.

### Legacy duplicate to retire
`GEO-Audit/app/main.py` contains a second agency welcome email sent over plain SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`), same subject "Welcome to Gatha: your login details". The live invite path is the Resend one in the web app. This SMTP copy is a leftover from before Resend. Two senders = two possible From addresses for the same email. **Remove it.** Nothing depends on it.

---

## 8. Database

Apply the files in `GEO-Audit/supabase/` in numeric order, `010` through `180`. All are idempotent.

### CRITICAL before taking real payments
`180_billing_integrity.sql` has **not been applied yet** and must be before taking real payments. It makes credit changes happen in a single statement. Without it, a purchase landing at the same moment as an audit can erase the other's write, wiping out credits somebody paid for. It also lets the billing ledger record a payment that could not be fulfilled, instead of losing it silently.

---

## 9. Local dev run

`start_env.bat` at the workspace root launches both apps:

- **app1** (engine): creates `.venv` if missing, installs `requirements.txt`, runs `uvicorn app.main:app --port 8080 --reload`
- **app2** (web app): runs `npm install` if needed, then `npm run dev` on `:3000`

Each app opens in its own window. Close a window to stop that app.

---

## 10. Build & deploy commands

**Web app:**
```bash
# set NEXT_PUBLIC_* before building - they are compiled in
npm install
npm run build
npm run start          # npm run dev for local work
```

**Audit engine:**
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
# production builds from the Dockerfile; Railway uses railway.toml
```

---

## 11. Open work items (from `todos/todo`)

Start now, no dependency:

- [ ] Continue with Google sign-in
- [ ] Products & services chips (already in progress)
- [ ] Dark / light themes
- [ ] Integrations directory + one-way send to Notion / Asana / Slack
- [ ] GSC / GA4 OAuth connect (build the connection, defer what it feeds)
- [ ] Compare markets (comparison layer on existing data)
- [ ] Super-admin: agencies list, admin overview, cost-vs-income dashboard
- [ ] Terms of Service, Privacy Policy
- [ ] GHL contact sync
- [ ] AI Site Health crawler - independent of the fixes, but still needs scoring criteria first

---

## 12. Pre-launch checklist (blockers for going live)

- [ ] **Apply `180_billing_integrity.sql`** before taking any real payment (prevents credit-write race).
- [ ] **Decide on the audit-tier problem**: $19/$49/$79 all grant the same audit. Either build the per-tier limits (25/50/100 prompts, 3/5/5 engines) or reprice/relabel.
- [ ] **Move accounts into the client's name** (GoDaddy, Hostinger, Supabase, OpenRouter, Resend, SerpAPI) and rotate shared credentials.
- [ ] **Set live Stripe keys** on the engine and point the Stripe webhook endpoint at it.
- [ ] **Remove the SMTP duplicate invite** in `GEO-Audit/app/main.py`.
- [ ] **Verify `NEXT_PUBLIC_SITE_URL`** - wrong value breaks every emailed login/reset link.
- [ ] **Set `NEXT_PUBLIC_ALLOW_INDEXING=true`** on production only.
