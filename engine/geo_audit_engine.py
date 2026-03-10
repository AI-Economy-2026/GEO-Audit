#!/usr/bin/env python3
"""
GEO Audit Engine (Web Worker Edition)
======================================
Core audit logic extracted for use by the FastAPI worker.
All query functions and analysis logic are identical to the CLI version.

The only change: run_audit() accepts an optional progress_callback.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Third-party imports (graceful degradation)
# ---------------------------------------------------------------------------
try:
    import openai
except ImportError:
    openai = None  # type: ignore[assignment]

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUPPORTED_ENGINES = (
    "openai", "anthropic", "google", "perplexity", "xai",
    "deepseek", "meta_llama", "google_ai_mode", "google_ai_overview",
    "bing_copilot",
)

ENGINE_DISPLAY_NAMES = {
    "openai": "OpenAI (ChatGPT)",
    "anthropic": "Anthropic (Claude)",
    "google": "Google (Gemini)",
    "perplexity": "Perplexity",
    "xai": "xAI (Grok)",
    "deepseek": "DeepSeek",
    "meta_llama": "Meta (Llama)",
    "google_ai_mode": "Google AI Mode",
    "google_ai_overview": "Google AI Overview",
    "bing_copilot": "Bing (Copilot)",
}

ENGINE_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
    "google": "gemini-2.5-flash",
    "perplexity": "sonar-pro",
    "xai": "grok-3",
    "deepseek": "deepseek-chat",
    "meta_llama": "Llama-4-Maverick-17B-128E-Instruct-FP8",
}

RATE_LIMIT_SECONDS = 1.0
MAX_RETRIES = 1

# Per-engine rate limits for parallel execution
ENGINE_RATE_LIMITS = {
    "openai": 0.5,
    "anthropic": 1.0,
    "google": 0.5,
    "perplexity": 1.0,
    "xai": 1.0,
    "deepseek": 1.0,
    "meta_llama": 1.0,
    "google_ai_mode": 2.0,
    "google_ai_overview": 2.0,
    "bing_copilot": 2.0,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Prompt:
    prompt_id: int
    category: str
    prompt_text: str


@dataclass
class AuditResult:
    prompt_id: int
    category: str
    prompt_text: str
    engine: str
    brand_mentioned: bool = False
    position_rank: Optional[int] = None
    url_cited: bool = False
    competitor_mentions: list[str] = field(default_factory=list)
    sentiment: str = "neutral"
    response_text: str = ""
    timestamp: str = ""


# Type alias for the progress callback
ProgressCallback = Callable[[int, int, AuditResult], None]


# ---------------------------------------------------------------------------
# API query functions (all identical to CLI version)
# ---------------------------------------------------------------------------
def query_openai(prompt_text: str) -> str:
    if openai is None:
        raise ImportError("openai library is not installed.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set.")
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=ENGINE_MODELS["openai"],
        messages=[{"role": "user", "content": prompt_text}],
        temperature=0.2,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


def query_anthropic(prompt_text: str) -> str:
    if anthropic is None:
        raise ImportError("anthropic library is not installed.")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set.")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=ENGINE_MODELS["anthropic"],
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt_text}],
    )
    return "".join(
        block.text for block in message.content if hasattr(block, "text")
    )


def query_google(prompt_text: str) -> str:
    import urllib.request
    import urllib.error

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY is not set.")
    model = ENGINE_MODELS["google"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["candidates"][0]["content"]["parts"][0]["text"]


def query_perplexity(prompt_text: str) -> str:
    if openai is None:
        raise ImportError("openai library is not installed.")
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise EnvironmentError("PERPLEXITY_API_KEY is not set.")
    client = openai.OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
    response = client.chat.completions.create(
        model=ENGINE_MODELS["perplexity"],
        messages=[{"role": "user", "content": prompt_text}],
        temperature=0.2,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


def query_xai(prompt_text: str) -> str:
    if openai is None:
        raise ImportError("openai library is not installed.")
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise EnvironmentError("XAI_API_KEY is not set.")
    client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    response = client.chat.completions.create(
        model=ENGINE_MODELS["xai"],
        messages=[{"role": "user", "content": prompt_text}],
        temperature=0.2,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


def query_deepseek(prompt_text: str) -> str:
    if openai is None:
        raise ImportError("openai library is not installed.")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPSEEK_API_KEY is not set.")
    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model=ENGINE_MODELS["deepseek"],
        messages=[{"role": "user", "content": prompt_text}],
        temperature=0.2,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


def query_meta_llama(prompt_text: str) -> str:
    if openai is None:
        raise ImportError("openai library is not installed.")
    api_key = os.getenv("META_LLAMA_API_KEY")
    if not api_key:
        raise EnvironmentError("META_LLAMA_API_KEY is not set.")
    client = openai.OpenAI(api_key=api_key, base_url="https://api.llama.com/compat/v1/")
    response = client.chat.completions.create(
        model=ENGINE_MODELS["meta_llama"],
        messages=[{"role": "user", "content": prompt_text}],
        temperature=0.2,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


def query_google_ai_mode(prompt_text: str) -> str:
    import urllib.request
    import urllib.error

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise EnvironmentError("SERPAPI_API_KEY is not set.")
    params = urllib.parse.urlencode({
        "engine": "google_ai_mode",
        "q": prompt_text,
        "api_key": api_key,
    })
    url = f"https://serpapi.com/search.json?{params}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if "markdown" in result and result["markdown"]:
        return result["markdown"]
    text_blocks = result.get("text_blocks", [])
    parts = []
    for block in text_blocks:
        if isinstance(block, dict):
            parts.append(block.get("text", block.get("snippet", "")))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts) if parts else "[NO RESPONSE] Google AI Mode returned no content."


def query_google_ai_overview(prompt_text: str) -> str:
    import urllib.request
    import urllib.error

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise EnvironmentError("SERPAPI_API_KEY is not set.")
    params = urllib.parse.urlencode({
        "engine": "google",
        "q": prompt_text,
        "api_key": api_key,
    })
    url = f"https://serpapi.com/search.json?{params}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    ai_overview = result.get("ai_overview", {})
    if not ai_overview:
        return "[NO RESPONSE] No AI Overview was generated for this query."
    if isinstance(ai_overview, dict):
        if "markdown" in ai_overview:
            return ai_overview["markdown"]
        text_blocks = ai_overview.get("text_blocks", [])
        parts = []
        for block in text_blocks:
            if isinstance(block, dict):
                parts.append(block.get("text", block.get("snippet", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts) if parts else str(ai_overview)
    return str(ai_overview)


def query_bing_copilot(prompt_text: str) -> str:
    import urllib.request
    import urllib.error

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise EnvironmentError("SERPAPI_API_KEY is not set.")
    params = urllib.parse.urlencode({
        "engine": "bing",
        "q": prompt_text,
        "api_key": api_key,
    })
    url = f"https://serpapi.com/search.json?{params}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    # Extract AI-generated content or organic snippets
    ai_overview = result.get("ai_overview", {})
    if ai_overview:
        if isinstance(ai_overview, dict) and "text" in ai_overview:
            return ai_overview["text"]
        return str(ai_overview)
    organic = result.get("organic_results", [])
    if organic:
        parts = []
        for r in organic[:5]:
            snippet = r.get("snippet", "")
            title = r.get("title", "")
            if snippet:
                parts.append(f"{title}: {snippet}")
        return "\n".join(parts) if parts else "[NO RESPONSE] Bing returned no content."
    return "[NO RESPONSE] Bing Copilot returned no content."


ENGINE_QUERY_FNS = {
    "openai": query_openai,
    "anthropic": query_anthropic,
    "google": query_google,
    "perplexity": query_perplexity,
    "xai": query_xai,
    "deepseek": query_deepseek,
    "meta_llama": query_meta_llama,
    "google_ai_mode": query_google_ai_mode,
    "google_ai_overview": query_google_ai_overview,
    "bing_copilot": query_bing_copilot,
}

# Map engine to required env var
ENGINE_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "meta_llama": "META_LLAMA_API_KEY",
    "google_ai_mode": "SERPAPI_API_KEY",
    "google_ai_overview": "SERPAPI_API_KEY",
    "bing_copilot": "SERPAPI_API_KEY",
}


# ---------------------------------------------------------------------------
# Response analysis (identical to CLI version)
# ---------------------------------------------------------------------------
def analyse_response(
    response_text: str,
    brand: str,
    url: str,
    competitors: list[str],
) -> dict:
    text_lower = response_text.lower()
    brand_lower = brand.lower()
    brand_mentioned = brand_lower in text_lower
    url_normalised = url.lower().replace("https://", "").replace("http://", "").replace("www.", "")
    url_cited = url_normalised in text_lower
    position_rank = _detect_list_position(response_text, brand)
    competitor_mentions = [
        comp for comp in competitors
        if comp.strip() and comp.strip().lower() in text_lower
    ]
    sentiment = _detect_sentiment(response_text, brand)
    return {
        "brand_mentioned": brand_mentioned,
        "position_rank": position_rank,
        "url_cited": url_cited,
        "competitor_mentions": competitor_mentions,
        "sentiment": sentiment,
    }


def _detect_list_position(response_text: str, brand: str) -> Optional[int]:
    brand_lower = brand.lower()
    pattern = re.compile(
        r"^\s*(\d{1,2})\s*[.):\-]\s*[*_]{0,2}\s*(.*)",
        re.MULTILINE,
    )
    for match in pattern.finditer(response_text):
        rank = int(match.group(1))
        item_text = match.group(2).lower()
        if brand_lower in item_text:
            return rank
    return None


def _detect_sentiment(response_text: str, brand: str) -> str:
    brand_lower = brand.lower()
    text_lower = response_text.lower()
    if brand_lower not in text_lower:
        return "neutral"
    sentences = re.split(r"[.!?\n]", response_text)
    brand_sentences = [s for s in sentences if brand_lower in s.lower()]
    if not brand_sentences:
        return "neutral"
    positive_words = {
        "leading", "top", "best", "excellent", "strong", "trusted",
        "reputable", "reliable", "innovative", "award", "recommended",
        "established", "comprehensive", "outstanding", "premier",
        "well-known", "renowned", "respected", "experienced", "expertise",
        "specialise", "specialize", "certified", "accredited",
        "high-quality", "proven", "robust", "partner",
    }
    negative_words = {
        "poor", "weak", "lacks", "limited", "outdated", "expensive",
        "complaints", "issues", "problems", "concerns", "behind",
        "struggling", "declining", "negative", "worst", "avoid",
        "disappointing", "inferior", "unreliable",
    }
    combined = " ".join(brand_sentences).lower()
    pos_count = sum(1 for w in positive_words if w in combined)
    neg_count = sum(1 for w in negative_words if w in combined)
    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    return "neutral"


# ---------------------------------------------------------------------------
# Core audit loop (with progress_callback)
# ---------------------------------------------------------------------------
def run_audit(
    prompts: list[Prompt],
    brand: str,
    url: str,
    competitors: list[str],
    engines: list[str],
    dry_run: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> list[AuditResult]:
    """
    Run every prompt through every requested engine.

    If progress_callback is provided, it is called after each query with:
        progress_callback(completed_count, total_count, result)
    """
    results: list[AuditResult] = []
    total_tasks = len(prompts) * len(engines)
    completed = 0

    for prompt in prompts:
        for engine in engines:
            completed += 1
            display = ENGINE_DISPLAY_NAMES.get(engine, engine)

            result = AuditResult(
                prompt_id=prompt.prompt_id,
                category=prompt.category,
                prompt_text=prompt.prompt_text,
                engine=engine,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

            if dry_run:
                result.response_text = "[DRY RUN] No API call made."
                results.append(result)
                if progress_callback:
                    progress_callback(completed, total_tasks, result)
                continue

            # Query the engine with retry logic
            query_fn = ENGINE_QUERY_FNS[engine]
            response_text = ""
            success = False

            for attempt in range(1, MAX_RETRIES + 2):
                try:
                    response_text = query_fn(prompt.prompt_text)
                    success = True
                    break
                except Exception as exc:
                    if attempt <= MAX_RETRIES:
                        time.sleep(RATE_LIMIT_SECONDS)
                    else:
                        response_text = f"[ERROR] {exc.__class__.__name__}: {exc}"

            if success:
                analysis = analyse_response(response_text, brand, url, competitors)
                result.brand_mentioned = analysis["brand_mentioned"]
                result.position_rank = analysis["position_rank"]
                result.url_cited = analysis["url_cited"]
                result.competitor_mentions = analysis["competitor_mentions"]
                result.sentiment = analysis["sentiment"]
                result.response_text = response_text
            else:
                result.response_text = response_text

            results.append(result)

            # Notify progress
            if progress_callback:
                progress_callback(completed, total_tasks, result)

            # Rate limiting
            time.sleep(RATE_LIMIT_SECONDS)

    return results


# ---------------------------------------------------------------------------
# Summary generation (returns dict, no file I/O)
# ---------------------------------------------------------------------------
def generate_summary_dict(
    results: list[AuditResult],
    brand: str,
) -> dict:
    """Generate aggregate statistics as a dict (no file writing)."""
    valid_results = [r for r in results if not r.response_text.startswith("[ERROR]")]
    total_prompts = len({r.prompt_id for r in valid_results})

    # Per-engine
    engine_stats: dict[str, dict] = {}
    for engine in {r.engine for r in valid_results}:
        engine_results = [r for r in valid_results if r.engine == engine]
        mentioned = sum(1 for r in engine_results if r.brand_mentioned)
        url_cited = sum(1 for r in engine_results if r.url_cited)
        avg_rank_values = [r.position_rank for r in engine_results if r.position_rank is not None]
        avg_rank = round(sum(avg_rank_values) / len(avg_rank_values), 1) if avg_rank_values else None
        engine_stats[engine] = {
            "display_name": ENGINE_DISPLAY_NAMES.get(engine, engine),
            "total_queries": len(engine_results),
            "brand_mentioned": mentioned,
            "visibility_rate": round(mentioned / len(engine_results) * 100, 1) if engine_results else 0,
            "url_cited_count": url_cited,
            "url_citation_rate": round(url_cited / len(engine_results) * 100, 1) if engine_results else 0,
            "average_rank": avg_rank,
        }

    # Overall
    total_valid = len(valid_results)
    total_mentioned = sum(1 for r in valid_results if r.brand_mentioned)
    overall_visibility = round(total_mentioned / total_valid * 100, 1) if total_valid else 0

    # Categories
    categories: dict[str, dict] = {}
    for cat in {r.category for r in valid_results}:
        cat_results = [r for r in valid_results if r.category == cat]
        cat_mentioned = sum(1 for r in cat_results if r.brand_mentioned)
        categories[cat] = {
            "total_queries": len(cat_results),
            "brand_mentioned": cat_mentioned,
            "visibility_rate": round(cat_mentioned / len(cat_results) * 100, 1) if cat_results else 0,
        }

    # Competitors
    competitor_counts: dict[str, int] = {}
    for r in valid_results:
        for comp in r.competitor_mentions:
            competitor_counts[comp] = competitor_counts.get(comp, 0) + 1
    sorted_competitors = sorted(competitor_counts.items(), key=lambda x: x[1], reverse=True)

    # Sentiment
    sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for r in valid_results:
        if r.brand_mentioned:
            sentiment_counts[r.sentiment] = sentiment_counts.get(r.sentiment, 0) + 1

    return {
        "audit_metadata": {
            "brand": brand,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_prompts": total_prompts,
            "total_queries": total_valid,
            "errors": len(results) - len(valid_results),
        },
        "overall_visibility": {
            "brand_mentioned_count": total_mentioned,
            "visibility_rate_percent": overall_visibility,
        },
        "engine_breakdown": engine_stats,
        "category_performance": categories,
        "competitor_analysis": {
            "mention_counts": dict(sorted_competitors),
            "most_mentioned": sorted_competitors[0][0] if sorted_competitors else None,
        },
        "sentiment_breakdown": sentiment_counts,
    }


# ---------------------------------------------------------------------------
# Async audit loop (engine-level parallelism)
# ---------------------------------------------------------------------------
async def _run_engine_prompts(
    engine: str,
    prompts: list[Prompt],
    brand: str,
    url: str,
    competitors: list[str],
    executor: ThreadPoolExecutor,
    progress_lock: asyncio.Lock,
    progress_counter: list[int],
    total_tasks: int,
    progress_callback: Optional[ProgressCallback],
) -> list[AuditResult]:
    """Run all prompts for a single engine sequentially with rate limiting."""
    results: list[AuditResult] = []
    rate_limit = ENGINE_RATE_LIMITS.get(engine, 1.0)
    loop = asyncio.get_event_loop()

    for prompt in prompts:
        result = AuditResult(
            prompt_id=prompt.prompt_id,
            category=prompt.category,
            prompt_text=prompt.prompt_text,
            engine=engine,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        query_fn = ENGINE_QUERY_FNS[engine]
        response_text = ""
        success = False

        for attempt in range(1, MAX_RETRIES + 2):
            try:
                response_text = await loop.run_in_executor(
                    executor, query_fn, prompt.prompt_text
                )
                success = True
                break
            except Exception as exc:
                if attempt <= MAX_RETRIES:
                    await asyncio.sleep(rate_limit)
                else:
                    response_text = f"[ERROR] {exc.__class__.__name__}: {exc}"

        if success:
            analysis = analyse_response(response_text, brand, url, competitors)
            result.brand_mentioned = analysis["brand_mentioned"]
            result.position_rank = analysis["position_rank"]
            result.url_cited = analysis["url_cited"]
            result.competitor_mentions = analysis["competitor_mentions"]
            result.sentiment = analysis["sentiment"]
            result.response_text = response_text
        else:
            result.response_text = response_text

        results.append(result)

        # Thread-safe progress update
        async with progress_lock:
            progress_counter[0] += 1
            completed = progress_counter[0]

        if progress_callback:
            progress_callback(completed, total_tasks, result)

        # Rate limiting between prompts
        await asyncio.sleep(rate_limit)

    return results


async def run_audit_async(
    prompts: list[Prompt],
    brand: str,
    url: str,
    competitors: list[str],
    engines: list[str],
    progress_callback: Optional[ProgressCallback] = None,
) -> list[AuditResult]:
    """
    Run the audit with engine-level parallelism.

    Each engine processes all prompts sequentially (respecting its rate limit),
    but all engines run concurrently via asyncio.gather().
    """
    total_tasks = len(prompts) * len(engines)
    progress_lock = asyncio.Lock()
    progress_counter = [0]

    executor = ThreadPoolExecutor(max_workers=len(engines))

    try:
        tasks = [
            _run_engine_prompts(
                engine=engine,
                prompts=prompts,
                brand=brand,
                url=url,
                competitors=competitors,
                executor=executor,
                progress_lock=progress_lock,
                progress_counter=progress_counter,
                total_tasks=total_tasks,
                progress_callback=progress_callback,
            )
            for engine in engines
        ]

        engine_results = await asyncio.gather(*tasks)

        # Flatten results
        all_results: list[AuditResult] = []
        for result_list in engine_results:
            all_results.extend(result_list)

        return all_results
    finally:
        executor.shutdown(wait=False)
