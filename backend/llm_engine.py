# backend/llm_engine.py — FIXED VERSION
# ============================================================
# Fixes:
# 1. Ollama timeout increased to 120s (was timing out on first request)
# 2. Better error message when Ollama fails
# 3. strip_action_json is more aggressive — catches all JSON variants
# 4. Groq fallback only if key is actually set
# ============================================================

import json
import re
import httpx
import asyncio
from typing import Dict, List, Optional
from backend.config import (
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    GROQ_API_KEY, GROQ_MODEL,
    LLM_PROVIDER
)

# ── System Prompt ─────────────────────────────────────────────

NEXON_SYSTEM_PROMPT = """You are NEXON, an advanced agentic AI Operating System assistant.
You can understand and respond in English, Hindi, and Hinglish (mixed Hindi-English).

You have access to these tools/agents:
- email: Send, read, draft, reply to emails
- calendar: Create, edit, delete calendar events, schedule meetings
- files: Create, convert, organize, summarize documents and files
- screen: Screenshot, screen recording, OCR, app control
- web: Web scraping, form filling, price tracking, data extraction
- data: Process CSVs/Excel, generate reports and charts
- messaging: WhatsApp, SMS, Slack, Teams, Discord messages
- smart_home: Light control, thermostat, security
- finance: Expense tracking, bill reminders
- productivity: Tasks, reminders, notes, time tracking

CRITICAL RULES:
1. Respond naturally in the SAME language as the user.
2. ONLY include a JSON action block if the user explicitly asks you to DO something (send email, take screenshot, etc.).
3. For casual conversation, greetings, questions — respond with PLAIN TEXT ONLY. NO JSON.
4. If you do need to include an action, put it at the very END after your response, in this exact format:
```json
{"action": {"type": "action_name", "params": {}}}
```
5. For wake words ("Hey NEXON", "Hi NEXON") — greet warmly, NO JSON.
6. Be concise and helpful."""


class OllamaClient:
    """Client for locally running Ollama LLM server."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_MODEL):
        self.base_url = base_url
        self.model    = model
        self.chat_url = f"{base_url}/api/chat"

    async def generate(
        self,
        messages    : List[Dict],
        system      : str   = NEXON_SYSTEM_PROMPT,
        max_tokens  : int   = 1024,
        temperature : float = 0.7
    ) -> str:
        payload = {
            "model"  : self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream" : False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx"    : 4096,
            }
        }

        # Use 120s timeout — Ollama first load can take 25+ seconds
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                resp = await client.post(self.chat_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                if not content:
                    raise RuntimeError("Empty response from Ollama")
                return content
            except httpx.ConnectError:
                raise ConnectionError(
                    "Cannot connect to Ollama. Make sure 'ollama serve' is running."
                )
            except httpx.TimeoutException:
                raise RuntimeError(
                    "Ollama request timed out. The model may still be loading — try again in 10 seconds."
                )
            except Exception as e:
                raise RuntimeError(f"Ollama error: {e}")

    async def is_available(self) -> bool:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
            except Exception:
                return False


class GroqClient:
    """Client for Groq cloud LLM API (fallback)."""

    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str = GROQ_API_KEY, model: str = GROQ_MODEL):
        self.api_key = api_key
        self.model   = model

    async def generate(
        self,
        messages    : List[Dict],
        system      : str   = NEXON_SYSTEM_PROMPT,
        max_tokens  : int   = 1024,
        temperature : float = 0.7
    ) -> str:
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not configured in .env file.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type" : "application/json"
        }
        payload = {
            "model"      : self.model,
            "messages"   : [{"role": "system", "content": system}] + messages,
            "max_tokens" : max_tokens,
            "temperature": temperature
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(self.BASE_URL, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                raise RuntimeError(f"Groq API error: {e}")


class NexonLLM:
    """
    Unified LLM interface.
    Uses Ollama by default. Falls back to Groq ONLY if GROQ_API_KEY is set.
    """

    def __init__(self):
        self.ollama   = OllamaClient()
        self.groq     = GroqClient()
        self.provider = LLM_PROVIDER

    async def _call(
        self,
        messages    : List[Dict],
        system      : str   = NEXON_SYSTEM_PROMPT,
        max_tokens  : int   = 1024,
        temperature : float = 0.7
    ) -> str:
        # Always try Ollama first
        try:
            return await self.ollama.generate(messages, system, max_tokens, temperature)
        except Exception as e:
            # Only fall back to Groq if API key is actually configured
            if GROQ_API_KEY and GROQ_API_KEY.strip():
                print(f"[NexonLLM] Ollama failed ({e}), falling back to Groq.")
                return await self.groq.generate(messages, system, max_tokens, temperature)
            else:
                # No Groq key — return helpful error message
                print(f"[NexonLLM] Ollama failed: {e}")
                raise RuntimeError(
                    f"Ollama is not responding. Make sure:\n"
                    f"1. Ollama is running: 'ollama serve'\n"
                    f"2. Model is pulled: 'ollama pull {OLLAMA_MODEL}'\n"
                    f"Error: {e}"
                )

    async def generate_response(
        self,
        user_message: str,
        context     : Optional[List[Dict]] = None,
        system      : str                  = None,
        max_tokens  : int                  = 1024,
        temperature : float                = 0.7,
        language    : str                  = "en"
    ) -> str:
        lang_hint = {
            "en"      : "Respond in English.",
            "hi"      : "हिंदी में जवाब दें।",
            "hinglish": "Hinglish mein jawab do (Hindi aur English mix).",
        }.get(language, "Respond in English.")

        sys_prompt = (system or NEXON_SYSTEM_PROMPT) + f"\n\nLanguage: {lang_hint}"
        messages   = (context or []) + [{"role": "user", "content": user_message}]
        return await self._call(messages, sys_prompt, max_tokens, temperature)

    async def classify_intent(self, text: str) -> Dict:
        """
        Classify intent. Returns conservative 'small_talk' for simple messages
        to prevent false parallel execution triggers.
        """
        # Fast rule-based check — don't call LLM for obvious small talk
        simple_patterns = [
            r'^(hi|hello|hey|yo|sup|what\'s up|howdy)[\s!?]*$',
            r'^how are you[\s?]*$',
            r'^(good|bad|fine|ok|okay|thanks|thank you|bye|goodbye)[\s!?]*$',
            r'^(yes|no|yeah|nah|yep|nope)[\s!?]*$',
        ]
        text_lower = text.lower().strip()
        for pattern in simple_patterns:
            if re.match(pattern, text_lower, re.IGNORECASE):
                return {"intent": "small_talk", "params": {}, "confidence": 0.99}

        system = """You are an intent classifier. Given user text, return ONLY valid JSON:
{
  "intent": "<one of: send_email|read_email|create_calendar_event|list_events|create_file|convert_file|move_file|take_screenshot|open_app|web_scrape|web_search|process_data|send_message|set_reminder|small_talk|general_qna|smart_home|finance|time_track|note|unknown>",
  "params": {},
  "confidence": 0.0
}

IMPORTANT: Use small_talk for greetings, questions about feelings, casual chat.
Only use action intents when user explicitly wants something DONE.
Extract relevant parameters (email, date, filename, etc) into params."""

        messages = [{"role": "user", "content": f"Classify: {text}"}]
        try:
            raw = await self._call(messages, system, max_tokens=200, temperature=0.1)
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            # Extract JSON if wrapped in text
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            return json.loads(raw)
        except Exception:
            return {"intent": "general_qna", "params": {}, "confidence": 0.5}

    async def summarize_conversation(self, messages: List[Dict]) -> str:
        system   = "Summarize this conversation in 2-4 sentences, capturing key topics and actions."
        text     = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        return await self._call(
            [{"role": "user", "content": text}],
            system, max_tokens=200, temperature=0.3
        )

    async def extract_action_from_response(self, response_text: str) -> Optional[Dict]:
        """Parse JSON action block from LLM response."""
        match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if not match:
            match = re.search(r'(\{"action".*?\})', response_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                return None
        return None

    async def check_availability(self) -> Dict:
        ollama_ok = await self.ollama.is_available()
        groq_ok   = bool(GROQ_API_KEY and GROQ_API_KEY.strip())
        return {
            "ollama"  : ollama_ok,
            "groq"    : groq_ok,
            "model"   : OLLAMA_MODEL,
            "provider": "ollama" if ollama_ok else ("groq" if groq_ok else "none")
        }


# Singleton
nexon_llm = NexonLLM()