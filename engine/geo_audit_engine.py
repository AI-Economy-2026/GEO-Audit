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
import logging

# from tenacity import (
#     retry,
#     stop_after_attempt,
#     wait_exponential,
#     retry_if_exception_type,
#     before_sleep_log
# )

logger = logging.getLogger(__name__)

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
    "google_ai_mode": 4.0,
    "google_ai_overview": 4.0,
    "bing_copilot": 4.0,
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class SerpApiFatalError(Exception):
    """Exception raised for non-retriable SerpApi errors (e.g., out of search credits)."""
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Prompt:
    prompt_id: int
    category: str
    prompt_text: str
    prompt_type: str = "ranking"


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
    excerpt: Optional[str] = None
    citation_data: dict = field(default_factory=lambda: {"cited": False, "all_citations": [], "citation_position": None})


# Type alias for the progress callback
ProgressCallback = Callable[[int, int, AuditResult], None]


# ---------------------------------------------------------------------------
# API query functions (all identical to CLI version)
# ---------------------------------------------------------------------------

#  = retry(
#     retry=retry_if_exception_type(Exception),
#     wait=wait_exponential(multiplier=1, min=2, max=60),
#     stop=stop_after_attempt(5),
#     before_sleep=before_sleep_log(logger, logging.WARNING),
#     reraise=True
# )

# _serpapi = retry(
#     retry=retry_if_exception_type(Exception) & ~retry_if_exception_type(SerpApiFatalError),
#     wait=wait_exponential(multiplier=2, min=4, max=120),
#     stop=stop_after_attempt(10),
#     before_sleep=before_sleep_log(logger, logging.WARNING),
#     reraise=True
# )


def query_openai(prompt_text: str) -> str:
    print("prompt_text", prompt_text)
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
    print("response by openai", response)
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
    print("response by anthropic", message)
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
    print("response by perplexity", response)
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
    print("response by xai", response)
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
    print("response by deepseek", response)
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
    print("response by query_meta_llama", response)
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
    url = f"https://www.searchapi.io/api/v1/search?{params}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error(f"SearchAPI Error (Google AI Mode): {error_body}")
        if "out of searches" in error_body.lower() or e.code in [400, 401, 403]:
            raise SerpApiFatalError(f"SearchAPI Fatal {e.code}: {error_body}") from e
        raise Exception(f"SearchAPI HTTP {e.code}: {error_body}") from e
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
    url = f"https://www.searchapi.io/api/v1/search?{params}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error(f"SearchAPI Error (Google AI Overview): {error_body}")
        if "out of searches" in error_body.lower() or e.code in [400, 401, 403]:
            raise SerpApiFatalError(f"SearchAPI Fatal {e.code}: {error_body}") from e
        raise Exception(f"SearchAPI HTTP {e.code}: {error_body}") from e
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
    url = f"https://www.searchapi.io/api/v1/search?{params}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error(f"SearchAPI Error (Bing Copilot): {error_body}")
        if "out of searches" in error_body.lower() or e.code in [400, 401, 403]:
            raise SerpApiFatalError(f"SearchAPI Fatal {e.code}: {error_body}") from e
        raise Exception(f"SearchAPI HTTP {e.code}: {error_body}") from e
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
# Response analysis (LLM-based)
# ---------------------------------------------------------------------------

async def _llm_detect_brand(response_text: str, brand: str) -> dict:
    """
    Uses gpt-4o-mini to determine if brand is mentioned/recommended.
    """
    prompt = f"""Analyze this AI-generated response and determine if the 
company "{brand}" is mentioned or recommended.

Response text:
{response_text[:3000]}

Return ONLY a JSON object with no explanation, no markdown, no backticks:
{{
  "mentioned": true or false,
  "recommended": true or false,
  "position": null or integer (1 if first recommendation, 2 if second, etc),
  "excerpt": null or the exact sentence where the brand appears
}}

Rules:
- "mentioned" = brand appears in any context
- "recommended" = brand is actively suggested as a good option
- Be strict about brand matching — "{brand}" should be matched exactly. Partial matches within other words are NOT matches.
- If brand does not appear at all, return mentioned: false, 
  recommended: false, position: null, excerpt: null"""

    try:
        if openai is None:
            raise ImportError("openai library is not installed.")
        client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=150
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"LLM brand detect failed: {e}")
        # Fallback to basic string match if LLM call fails
        mentioned = brand.lower() in response_text.lower()
        return {
            "mentioned": mentioned,
            "recommended": mentioned,
            "position": None,
            "excerpt": None
        }


async def _llm_detect_sentiment(excerpt: str, brand: str) -> str:
    """
    Classifies how the brand is discussed in the given excerpt.
    Returns one of: "Positive", "Neutral", "Negative", "Not Mentioned"
    """
    if not excerpt:
        return "Not Mentioned"
    
    prompt = f"""How is the company "{brand}" discussed in this text?

Text: {excerpt}

Return ONLY one of these three words, nothing else:
positive
neutral  
negative

Rules:
- positive = actively praised or recommended
- neutral = mentioned factually without strong opinion
- negative = criticized, warned against, portrays poorly, or explicitly not recommended"""

    try:
        client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10
        )
        result = response.choices[0].message.content.strip().lower()
        if result in ["positive", "neutral", "negative"]:
            return result
        return "neutral"
    except Exception as e:
        logger.error(f"LLM sentiment detect failed: {e}")
        return "neutral"  # Safe fallback

def parse_citations(response_text: str, target_url: str) -> dict:
    """
    Extracts all citations from LLM response and checks if target_url
    is cited.
    """
    import re
    
    all_urls = []
    
    # Format 1: [Text](URL)
    inline_links = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', 
                              response_text)
    all_urls.extend([url for _, url in inline_links])
    
    # Format 2 & 3: [1]: URL or [^1]: URL
    ref_links = re.findall(r'\[\^?\d+\]:\s*(https?://\S+)', response_text)
    all_urls.extend(ref_links)
    
    # Format 4: bare URLs
    bare_urls = re.findall(r'(?<!\()(https?://[^\s\)\]\,]+)', response_text)
    all_urls.extend(bare_urls)
    
    # Format 5: numbered list references
    numbered_refs = re.findall(r'^\d+\.\s+(https?://\S+)', 
                               response_text, re.MULTILINE)
    all_urls.extend(numbered_refs)
    
    # Deduplicate
    all_urls = list(set(all_urls))
    
    # Check if target URL is in citations
    target_domain = target_url.lower().replace('https://', '')\
                                      .replace('http://', '')\
                                      .replace('www.', '')\
                                      .split('/')[0]
    
    cited = False
    citation_position = None
    
    for i, url in enumerate(all_urls):
        url_clean = url.lower().replace('https://', '')\
                               .replace('http://', '')\
                               .replace('www.', '')
        if target_domain in url_clean or url_clean.startswith(target_domain):
            cited = True
            citation_position = i + 1
            break
    
    return {
        "cited": cited,
        "all_citations": all_urls,
        "citation_position": citation_position
    }

async def analyse_response(
    response_text: str,
    brand: str,
    url: str,
    competitors: list[str],
) -> dict:
    text_lower = response_text.lower()
    brand_lower = brand.lower()
    
    # Use LLM logic for brand detection
    brand_data = await _llm_detect_brand(response_text, brand)
    brand_mentioned = brand_data["mentioned"]
    
    # Citation footnote parser
    citation_data = parse_citations(response_text, url)
    url_cited = citation_data["cited"]
    
    position_rank = brand_data.get("position") or _detect_list_position(response_text, brand)
    
    competitor_mentions = [
        comp for comp in competitors
        if comp.strip() and comp.strip().lower() in text_lower
    ]
    
    # Use LLM logic for sentiment detection
    sentiment = await _llm_detect_sentiment(brand_data.get("excerpt") or response_text, brand)
    
    return {
        "brand_mentioned": brand_mentioned,
        "position_rank": position_rank,
        "url_cited": url_cited,
        "competitor_mentions": competitor_mentions,
        "sentiment": sentiment,
        "excerpt": brand_data.get("excerpt"),
        "citation_data": citation_data,
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
                    raw_response = query_fn(prompt.prompt_text)
                    success = True
                    break
                except Exception as exc:
                    if attempt <= MAX_RETRIES:
                        time.sleep(RATE_LIMIT_SECONDS)
                    else:
                        raw_response = f"[ERROR] {exc.__class__.__name__}: {exc}"

            if success:
                if isinstance(raw_response, dict):
                    response_text = raw_response.get("response_text", "")
                    result.scraper_status = raw_response.get("scraper_status", "success")
                    result.scraper_error = raw_response.get("scraper_error")
                else:
                    response_text = raw_response
                    result.scraper_status = "success"

                if result.scraper_status == "failed":
                    result.brand_mentioned = False
                    result.position_rank = None
                    result.url_cited = False
                    result.sentiment = "neutral"
                    result.response_text = response_text
                else:
                    # Wrap with asyncio.run since run_audit is a sync function
                    loop = asyncio.new_event_loop()
                    analysis = loop.run_until_complete(analyse_response(response_text, brand, url, competitors))
                    loop.close()
                    result.brand_mentioned = analysis["brand_mentioned"]
                    result.position_rank = analysis["position_rank"]
                    result.url_cited = analysis["url_cited"]
                    result.competitor_mentions = analysis["competitor_mentions"]
                    result.sentiment = analysis["sentiment"]
                    result.response_text = response_text
                    result.excerpt = analysis.get("excerpt")
                    result.citation_data = analysis.get("citation_data", {})
            else:
                result.response_text = str(raw_response)
                result.scraper_status = "failed"
                result.scraper_error = "Query failed"

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
                raw_response = await loop.run_in_executor(
                    executor, query_fn, prompt.prompt_text
                )
                success = True
                break
            except Exception as exc:
                if attempt <= MAX_RETRIES:
                    await asyncio.sleep(rate_limit)
                else:
                    raw_response = f"[ERROR] {exc.__class__.__name__}: {exc}"

        if success:
            if isinstance(raw_response, dict):
                response_text = raw_response.get("response_text", "")
                result.scraper_status = raw_response.get("scraper_status", "success")
                result.scraper_error = raw_response.get("scraper_error")
            else:
                response_text = raw_response
                result.scraper_status = "success"

            if result.scraper_status == "failed":
                result.brand_mentioned = False
                result.position_rank = None
                result.url_cited = False
                result.sentiment = "neutral"
                result.response_text = response_text
            else:
                analysis = await analyse_response(response_text, brand, url, competitors)
                result.brand_mentioned = analysis["brand_mentioned"]
                result.position_rank = analysis["position_rank"]
                result.url_cited = analysis["url_cited"]
                result.competitor_mentions = analysis["competitor_mentions"]
                result.sentiment = analysis["sentiment"]
                result.response_text = response_text
                result.excerpt = analysis.get("excerpt")
                result.citation_data = analysis.get("citation_data", {})
        else:
            result.response_text = str(raw_response)
            result.scraper_status = "failed"
            result.scraper_error = "Query failed"

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
