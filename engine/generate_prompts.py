import json
import logging
from openai import OpenAI
from app.config import OPENAI_API_KEY
from engine.text_clean import strip_em_dashes

logger = logging.getLogger(__name__)

client = OpenAI(api_key=OPENAI_API_KEY)

def generate_wizard_prompts(brand_name: str, brand_url: str, competitors: list[str], keywords: list[str]) -> dict:
    prompt_text = f"""
    You are an expert SEO and AI Search Strategist. 
    A user is setting up an AI Search visibility audit (Generative Engine Optimization) for their business.
    
    Context about the business:
    - Brand Name: {brand_name}
    - Website: {brand_url}
    - Competitors: {', '.join(competitors) if competitors else 'None provided'}
    - Target Keywords/Services: {', '.join(keywords) if keywords else 'None provided'}

    I need you to generate two lists of search queries (prompts) that real humans would type into tools like ChatGPT or Perplexity to find services like this.

    1. "Intent Prompts" (Generate exactly 5): Highly specific, long-tail questions a user would ask when looking for these exact services. 
       Example: "I am looking for a family lawyer in Melbourne that handles custody disputes." or "What are the best IT managed service providers for small businesses?"

    2. "Ranking Prompts" (Generate exactly 10): Broader category or comparison searches to see how the brand stacks up against competitors.
       Example: "Top 10 family lawyers in Victoria" or "Compare Deloitte and PwC for tax advisory."

    Do not use em dashes; use commas or full stops instead.

    Return EXACTLY a valid JSON object with the following schema, and NO other markdown or text:
    {{
      "intent_prompts": ["prompt 1", "prompt 2", "prompt 3", "prompt 4", "prompt 5"],
      "ranking_prompts": ["prompt 1", "prompt 2", "prompt 3", "prompt 4", "prompt 5", "prompt 6", "prompt 7", "prompt 8", "prompt 9", "prompt 10"]
    }}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a specialized JSON-outputting AI. Only return valid JSON."},
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("No content returned from OpenAI")
            
        data = json.loads(content)
        # Sanitize client-facing generated prompt strings
        for key in ("intent_prompts", "ranking_prompts"):
            if isinstance(data.get(key), list):
                data[key] = [strip_em_dashes(p) if isinstance(p, str) else p for p in data[key]]
        return data
    except Exception as e:
        logger.error(f"Error generating wizard prompts: {e}")
        # Return fallback generic prompts if the API fails
        return {
            "intent_prompts": [
                f"I need services related to {brand_name}. Any recommendations?",
                f"Who can help me with {keywords[0] if keywords else 'my problem'}?",
                f"Looking for alternatives to {competitors[0] if competitors else 'my current provider'}.",
                f"What is the best company for {keywords[0] if keywords else 'this service'}?",
                f"Can {brand_name} help me with my business needs?"
            ],
            "ranking_prompts": [
                f"Top companies for {keywords[0] if keywords else 'this service'}" for _ in range(10)
            ]
        }
