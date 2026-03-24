from playwright.async_api import async_playwright
import asyncio
import logging

logger = logging.getLogger(__name__)

# CSS selectors for Google AI Overview
AI_OVERVIEW_SELECTORS = [
    "[data-attrid='wa:/description']",
    ".kno-rdesc",
    "[jsname='yEVEwb']",
    ".aioverview-container",
    "[data-content-feature='1']",
    ".SGWbHf",                          # Common AI overview wrapper
    "div[data-async-context] .yDYNvb",  # Alternate selector
]

async def scrape_google_ai_overview(query: str) -> str | None:
    """
    Uses Playwright headless browser to scrape Google AI Overview.
    Returns the text content or None if not found.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                ]
            )
            
            context = await browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1280, 'height': 800}
            )
            
            page = await context.new_page()
            
            search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            
            await page.goto(search_url, wait_until='domcontentloaded', 
                           timeout=15000)
            
            # Wait for AI overview to load (it's async on Google's side)
            await page.wait_for_timeout(3000)
            
            # Try each selector
            for selector in AI_OVERVIEW_SELECTORS:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        if text and len(text.strip()) > 50:
                            await browser.close()
                            logger.info(
                                f"Playwright found AI Overview for: "
                                f"{query[:60]}"
                            )
                            return text.strip()
                except:
                    continue
            
            await browser.close()
            logger.info(
                f"Playwright: No AI Overview found for: {query[:60]}"
            )
            return None
            
    except Exception as e:
        logger.error(f"Playwright scraper failed: {str(e)}")
        return None

def try_playwright_fallback(query: str) -> str | None:
    """
    Synchronous wrapper for the async Playwright scraper.
    Called from the SerpApi silent failure handler.
    """
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            scrape_google_ai_overview(query)
        )
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Playwright fallback wrapper failed: {str(e)}")
        return None
