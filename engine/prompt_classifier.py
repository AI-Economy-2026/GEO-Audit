"""
Deterministic prompt classification.

Two pure functions: no LLM calls, no side effects.
Used by the worker to annotate prompts and results with
prompt_type and intent_type before storing to Supabase.
"""

import re


def classify_prompt_type(prompt_text: str) -> str:
    """
    Returns one of: 'comparison' | 'ranking' | 'reviews' | 'informational'
    """
    t = prompt_text.lower()
    if re.search(r'\b(vs|versus|compared to|comparison|compare)\b', t):
        return 'comparison'
    if re.search(r'\b(best|top|leading|ranked|ranking)\b', t):
        return 'ranking'
    if re.search(r'\b(review|reviews|alternative|alternatives|instead of)\b', t):
        return 'reviews'
    return 'informational'


def classify_intent_type(prompt_text: str) -> str:
    """
    Returns one of: 'commercial' | 'navigational' | 'informational'
    """
    t = prompt_text.lower()
    if re.search(r'\b(hire|agency|service|services|consultant|buy|pricing|price|cost|recommend|best|top)\b', t):
        return 'commercial'
    return 'informational'
