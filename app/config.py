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

# --- AI Engine API keys ---
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY: str = os.environ.get("GOOGLE_API_KEY", "")
PERPLEXITY_API_KEY: str = os.environ.get("PERPLEXITY_API_KEY", "")
XAI_API_KEY: str = os.environ.get("XAI_API_KEY", "")
DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
META_LLAMA_API_KEY: str = os.environ.get("META_LLAMA_API_KEY", "")
SERPAPI_API_KEY: str = os.environ.get("SERPAPI_API_KEY", "")
