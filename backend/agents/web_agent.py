# backend/agents/web_agent.py
# ============================================================
# NEXON Web Agent
# Web scraping, search, form filling, price tracking,
# and automated browser interactions.
# ============================================================

import re
import json
import asyncio
from typing import Dict, List, Optional
from urllib.parse import urlparse
import httpx
from backend.llm_engine import nexon_llm


class WebAgent:
    """
    Web automation agent for NEXON.

    Capabilities:
    - Scrape web pages: extract title, headings, text, links.
    - Web search using DuckDuckGo (no API key needed).
    - Price tracking across e-commerce pages.
    - Form filling and navigation (via Playwright).
    - Invoice/receipt downloading.
    - Convert web pages to PDF or Markdown.

    Dependencies:
        httpx, beautifulsoup4, playwright (optional for full automation).
    """

    async def handle(self, intent: str, params: Dict, session_id: str) -> Dict:
        """Route web intents to the appropriate handler."""
        handlers = {
            "web_scrape"  : self.scrape_url,
            "web_search"  : self.web_search,
            "price_track" : self.track_price,
            "form_fill"   : self.fill_form,
        }
        handler = handlers.get(intent, self._unknown)
        return await handler(params, session_id)

    # ──────────────────────────────────────────
    # Web Scraping
    # ──────────────────────────────────────────

    async def scrape_url(self, params: Dict, session_id: str) -> Dict:
        """
        Scrape a URL and extract structured content.

        Args:
            params: {
                url       (str)  : Target URL to scrape.
                extract   (str)  : What to extract: 'all'|'text'|'links'|'tables'|'images'.
                summarize (bool) : Whether to LLM-summarize the extracted text.
                question  (str)  : Specific question to answer from the page.
            }
        Returns:
            Extracted content and optionally an LLM summary.
        """
        url       = params.get("url", "")
        extract   = params.get("extract", "all")
        summarize = params.get("summarize", False)
        question  = params.get("question", "")

        if not url:
            return {
                "success": False,
                "message": "Please provide a URL to scrape.",
                "action" : {}
            }

        # Validate URL
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text

            soup  = BeautifulSoup(html, "html.parser")
            title = soup.title.string.strip() if soup.title else urlparse(url).netloc

            # Remove scripts and styles
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            # Extract content based on type
            result = {"title": title, "url": url}

            if extract in ("all", "text"):
                text = soup.get_text(separator="\n", strip=True)
                # Clean up excessive whitespace
                text = re.sub(r"\n{3,}", "\n\n", text)
                result["text"] = text[:5000]

            if extract in ("all", "links"):
                links = []
                for a in soup.find_all("a", href=True)[:20]:
                    href = a["href"]
                    if href.startswith("http"):
                        links.append({"text": a.get_text(strip=True)[:80], "url": href})
                result["links"] = links

            if extract in ("all", "headings"):
                headings = []
                for tag in soup.find_all(["h1", "h2", "h3"]):
                    text = tag.get_text(strip=True)
                    if text:
                        headings.append({"level": tag.name, "text": text})
                result["headings"] = headings[:20]

            if extract in ("all", "tables"):
                tables = []
                for table in soup.find_all("table")[:3]:
                    rows = []
                    for tr in table.find_all("tr")[:10]:
                        row = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                        rows.append(row)
                    tables.append(rows)
                result["tables"] = tables

            # Format response message
            msg_parts = [f"🌐 **{title}**\n`{url}`"]

            if "headings" in result and result["headings"]:
                h_list = "\n".join(
                    f"{'#' * int(h['level'][1:])} {h['text']}"
                    for h in result["headings"][:6]
                )
                msg_parts.append(f"\n**Headings:**\n{h_list}")

            if "text" in result:
                preview = result["text"][:400]
                msg_parts.append(f"\n**Content preview:**\n{preview}...")

            if "links" in result and result["links"]:
                link_list = "\n".join(
                    f"• [{l['text']}]({l['url']})" for l in result["links"][:5]
                )
                msg_parts.append(f"\n**Links:**\n{link_list}")

            # LLM summarization
            if summarize and "text" in result:
                summary = await nexon_llm.generate_response(
                    f"Summarize the key information from this webpage content:\n\n{result['text'][:3000]}",
                    language="en"
                )
                msg_parts.append(f"\n**Summary:**\n{summary}")

            # Answer specific question
            if question and "text" in result:
                answer = await nexon_llm.generate_response(
                    f"Based on this webpage content, answer the question: '{question}'\n\n"
                    f"Content:\n{result['text'][:3000]}",
                    language="en"
                )
                msg_parts.append(f"\n**Answer to '{question}':**\n{answer}")

            return {
                "success": True,
                "message": "\n".join(msg_parts),
                "action" : {"type": "web_scraped", "details": result}
            }

        except httpx.HTTPError as e:
            return {
                "success": False,
                "message": f"❌ Could not access {url}: {str(e)}",
                "action" : {}
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Scraping failed: {str(e)}",
                "action" : {}
            }

    # ──────────────────────────────────────────
    # Web Search (DuckDuckGo — no API key)
    # ──────────────────────────────────────────

    async def web_search(self, params: Dict, session_id: str) -> Dict:
        """
        Search the web using DuckDuckGo instant answers API.

        Args:
            params: {
                query   (str): Search query.
                results (int): Number of results (default 5).
            }
        """
        query   = params.get("query") or params.get("raw_text", "")
        n       = int(params.get("results", 5))

        if not query:
            return {"success": False, "message": "Please provide a search query.", "action": {}}

        try:
            # DuckDuckGo instant answer API
            ddg_url = "https://api.duckduckgo.com/"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(ddg_url, params={
                    "q": query, "format": "json", "no_redirect": "1", "no_html": "1"
                })
                data = resp.json()

            results = []

            # Abstract (top answer)
            if data.get("AbstractText"):
                results.append({
                    "title"  : data.get("Heading", "Answer"),
                    "snippet": data["AbstractText"][:300],
                    "url"    : data.get("AbstractURL", "")
                })

            # Related topics
            for topic in data.get("RelatedTopics", [])[:n]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title"  : topic.get("Text", "")[:60],
                        "snippet": topic.get("Text", "")[:200],
                        "url"    : topic.get("FirstURL", "")
                    })

            if not results:
                return {
                    "success": True,
                    "message": f"No instant results found for '{query}'. Try a more specific query.",
                    "action" : {"type": "web_search", "details": {"query": query}}
                }

            formatted = [f"🔍 **Search results for: '{query}'**\n"]
            for i, r in enumerate(results[:n], 1):
                formatted.append(
                    f"**{i}. {r['title']}**\n{r['snippet']}\n{r['url']}"
                )

            return {
                "success": True,
                "message": "\n\n".join(formatted),
                "action" : {"type": "web_search", "details": {"results": results, "query": query}}
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Search failed: {str(e)}",
                "action" : {}
            }

    # ──────────────────────────────────────────
    # Price Tracking
    # ──────────────────────────────────────────

    async def track_price(self, params: Dict, session_id: str) -> Dict:
        """
        Scrape and extract price from an e-commerce product page.

        Args:
            params: {
                url       (str): Product page URL.
                threshold (float): Alert if price drops below this value.
            }
        """
        url = params.get("url", "")
        if not url:
            return {"success": False, "message": "Please provide a product URL.", "action": {}}

        try:
            from bs4 import BeautifulSoup

            headers = {"User-Agent": "Mozilla/5.0 (compatible; NexonBot/1.0)"}
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                html = resp.text

            soup   = BeautifulSoup(html, "html.parser")
            title  = soup.title.string.strip() if soup.title else url

            # Try common price CSS classes/patterns
            price_text = None
            price_selectors = [
                {"class": re.compile(r"price", re.I)},
                {"id"   : re.compile(r"price", re.I)},
                {"class": re.compile(r"amount", re.I)},
            ]
            for sel in price_selectors:
                el = soup.find(["span", "div", "p"], sel)
                if el:
                    text = el.get_text(strip=True)
                    if any(c in text for c in ["$", "₹", "£", "€", "¥"]):
                        price_text = text
                        break

            # Regex fallback on full page text
            if not price_text:
                page_text  = soup.get_text()
                price_match = re.search(r"[\$₹£€¥]\s*[\d,]+\.?\d*", page_text)
                if price_match:
                    price_text = price_match.group(0)

            threshold = params.get("threshold")
            alert_msg = ""
            if threshold and price_text:
                price_num = float(re.sub(r"[^\d.]", "", price_text or "0") or 0)
                if price_num <= float(threshold):
                    alert_msg = f"\n\n🚨 **Price alert!** Current price {price_text} is below your threshold of {threshold}!"

            return {
                "success": True,
                "message": (
                    f"💰 **Price Check**\n"
                    f"**Product:** {title[:80]}\n"
                    f"**Current Price:** {price_text or 'Could not detect price'}\n"
                    f"**URL:** {url}"
                    f"{alert_msg}"
                ),
                "action" : {
                    "type"   : "price_tracked",
                    "details": {"title": title, "price": price_text, "url": url}
                }
            }
        except Exception as e:
            return {"success": False, "message": f"❌ Price tracking failed: {str(e)}", "action": {}}

    # ──────────────────────────────────────────
    # Form Filling (Playwright)
    # ──────────────────────────────────────────

    async def fill_form(self, params: Dict, session_id: str) -> Dict:
        """
        Auto-fill a web form using Playwright.

        Args:
            params: {
                url    (str) : Form page URL.
                fields (dict): Field name → value mapping.
                submit (bool): Whether to click submit after filling.
            }
        """
        url    = params.get("url", "")
        fields = params.get("fields", {})
        submit = params.get("submit", False)

        if not url or not fields:
            return {
                "success": False,
                "message": "Please provide a URL and the form fields to fill.",
                "action" : {}
            }

        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                page    = await browser.new_page()
                await page.goto(url, timeout=15000)

                filled = []
                for field_name, value in fields.items():
                    # Try by name, id, placeholder
                    for selector in [
                        f'[name="{field_name}"]',
                        f'[id="{field_name}"]',
                        f'[placeholder*="{field_name}"]'
                    ]:
                        try:
                            await page.fill(selector, str(value), timeout=3000)
                            filled.append(field_name)
                            break
                        except Exception:
                            continue

                if submit:
                    await page.click('button[type="submit"]', timeout=5000)
                    await page.wait_for_load_state("networkidle", timeout=10000)

                await browser.close()

            return {
                "success": True,
                "message": (
                    f"✅ Form filled successfully!\n"
                    f"Fields filled: {', '.join(filled)}\n"
                    f"{'Form submitted.' if submit else 'Not submitted (submit=False).'}"
                ),
                "action" : {"type": "form_filled", "details": {"fields": filled, "submitted": submit}}
            }
        except ImportError:
            return {
                "success": False,
                "message": "Playwright not installed. Run: pip install playwright && playwright install",
                "action" : {}
            }
        except Exception as e:
            return {"success": False, "message": f"❌ Form fill failed: {str(e)}", "action": {}}

    async def _unknown(self, params: Dict, session_id: str) -> Dict:
        return {"success": False, "message": "Unknown web action.", "action": {}}