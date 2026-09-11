"""Configuration loaded from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


# --- Supabase ---
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# --- Worker auth ---
WORKER_API_KEY: str = os.environ.get("WORKER_API_KEY", "")

# --- Token encryption (agency_integrations credentials) ---
# Shared with app2 (Node.js). app2 encrypts with AES-256-GCM, app1 decrypts.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY: str = os.environ.get("TOKEN_ENCRYPTION_KEY", "")

# --- Web app URL (for webhook dispatch via pg-boss) ---
WEB_APP_URL: str = os.environ.get("WEB_APP_URL", "")

# --- Stripe ---
STRIPE_SECRET_KEY: str = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# --- AI Engine API keys ---
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY: str = os.environ.get("GOOGLE_API_KEY", "")
PERPLEXITY_API_KEY: str = os.environ.get("PERPLEXITY_API_KEY", "")
XAI_API_KEY: str = os.environ.get("XAI_API_KEY", "")
DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
META_LLAMA_API_KEY: str = os.environ.get("META_LLAMA_API_KEY", "")
SERPAPI_API_KEY: str = os.environ.get("SERPAPI_API_KEY", "")
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")

# DataForSEO (SEO add-on)
DATAFORSEO_LOGIN: str = os.environ.get("DATAFORSEO_LOGIN", "")
DATAFORSEO_PASSWORD: str = os.environ.get("DATAFORSEO_PASSWORD", "")

# Google OAuth (GSC) — used by the Next.js app primarily; listed for ops parity
GOOGLE_OAUTH_CLIENT_ID: str = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET: str = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

# --- Token encryption (shared with app2 for agency_integrations) ---
TOKEN_ENCRYPTION_KEY: str = os.environ.get("TOKEN_ENCRYPTION_KEY", "")

# --- Per-audit cost tracking (cents) ---
# Used by the worker to compute audit_costs.cost_cents for the finance dashboard.
COST_PER_SERPAPI_CALL_CENTS: int = 4
COST_PER_DATAFORSEO_CALL_CENTS: int = 2
COST_PER_AI_1K_INPUT_TOKENS_CENTS: int = 3
COST_PER_AI_1K_OUTPUT_TOKENS_CENTS: int = 15
COST_PER_BACKLINKS_CALL_CENTS: int = 10
COST_PER_PAGE_CRAWLED_CENTS: int = 1
