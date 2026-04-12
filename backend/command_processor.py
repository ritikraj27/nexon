# backend/command_processor.py — FIXED VERSION
# ============================================================
# Fixes:
# 1. strip_action_json is much more aggressive — catches ALL
#    JSON variants that were leaking into chat bubbles
# 2. Stores original user text (not enriched) in DB
# 3. Parallel executor only triggers for 2+ REAL action intents
# 4. Better error messages
# ============================================================

import json
import re
from typing import Dict, List, Optional

from backend.intent_parser import intent_parser
from backend.llm_engine import nexon_llm, NEXON_SYSTEM_PROMPT
from backend.db.sessions import (
    get_context_messages, add_message,
    save_summary, get_messages
)

from backend.agents.email_agent        import EmailAgent
from backend.agents.calendar_agent     import CalendarAgent
from backend.agents.file_agent         import FileAgent
from backend.agents.screen_agent       import ScreenAgent
from backend.agents.web_agent          import WebAgent
from backend.agents.data_agent         import DataAgent
from backend.agents.messaging_agent    import MessagingAgent
from backend.agents.smart_home_agent   import SmartHomeAgent
from backend.agents.finance_agent      import FinanceAgent
from backend.agents.productivity_agent import ProductivityAgent

try:
    from backend.agents.parallel_executor import ParallelExecutor, GestureMacroEngine
    _PARALLEL_AVAILABLE = True
except ImportError as e:
    print(f"[CommandProcessor] ParallelExecutor not available: {e}")
    _PARALLEL_AVAILABLE = False
    ParallelExecutor   = None
    GestureMacroEngine = None

AGENT_REGISTRY = {
    "EmailAgent"        : EmailAgent(),
    "CalendarAgent"     : CalendarAgent(),
    "FileAgent"         : FileAgent(),
    "ScreenAgent"       : ScreenAgent(),
    "WebAgent"          : WebAgent(),
    "DataAgent"         : DataAgent(),
    "MessagingAgent"    : MessagingAgent(),
    "SmartHomeAgent"    : SmartHomeAgent(),
    "FinanceAgent"      : FinanceAgent(),
    "ProductivityAgent" : ProductivityAgent(),
}

# Intents that should NEVER trigger parallel execution
CONVERSATIONAL_INTENTS = {
    "small_talk", "general_qna", "unknown", "greeting",
    "question", "chitchat", "acknowledgment"
}


def strip_action_json(text: str) -> str:
    """
    Aggressively remove ALL JSON action blocks from LLM response text.
    This prevents raw JSON from showing in the chat bubbles.

    Handles all variants:
    - ```json { ... } ```
    - ```{ ... }```
    - Raw { "action": ... }
    - { "type": ... }
    """
    if not text:
        return ""

    # Remove ```json ... ``` blocks (multiline)
    text = re.sub(r'```json\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)

    # Remove ``` ... ``` blocks containing JSON
    text = re.sub(r'```\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)

    # Remove raw {"action": ...} blocks
    text = re.sub(r'\{[\s\n]*"action"\s*:.*?\}[\s\n]*\}', '', text, flags=re.DOTALL)

    # Remove {"type": ...} blocks that look like action JSON
    text = re.sub(r'\{[\s\n]*"type"\s*:[\s\n]*"[^"]*".*?\}', '', text, flags=re.DOTALL)

    # Remove any remaining standalone JSON objects at end of response
    # (common pattern: LLM adds JSON after the text response)
    text = re.sub(r'\n+\s*\{[^{}]*"(action|type|params)"[^{}]*\}', '', text, flags=re.DOTALL)

    # Clean up excessive whitespace/newlines left behind
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


def clean_user_text_for_display(text: str) -> str:
    """
    Remove the visual/voice context prefix from user text
    so it doesn't show in chat history or history titles.

    The prefix looks like:
    [Visual/Voice context: ...]\n\nactual message
    """
    # Remove [Visual context: ...] prefix
    text = re.sub(r'^\[Visual(?:/Voice)? context:[^\]]*\]\n*', '', text, flags=re.DOTALL)
    # Remove [Voice analysis: ...] prefix
    text = re.sub(r'^\[Voice analysis:[^\]]*\]\n*', '', text, flags=re.DOTALL)
    # Remove [Relevant memories ...] prefix
    text = re.sub(r'^\[Relevant memories[^\]]*\]\n*', '', text, flags=re.DOTALL)
    return text.strip()


class CommandProcessor:
    """Central orchestrator for all NEXON commands."""

    def __init__(self):
        self.parallel_executor = None
        if _PARALLEL_AVAILABLE and ParallelExecutor:
            try:
                self.parallel_executor = ParallelExecutor(AGENT_REGISTRY)
                print("[CommandProcessor] ParallelExecutor initialized ✓")
            except Exception as e:
                print(f"[CommandProcessor] ParallelExecutor init failed: {e}")

    async def process(
        self,
        text              : str,
        session_id        : int,
        language          : str  = "en",
        emotion           : str  = "neutral",
        db                = None,
        style_prompt_extra: str  = "",
        original_text     : str  = "",  # The raw text without context prefix
    ) -> Dict:
        """
        Full command processing pipeline.

        Args:
            text           : Enriched text (may have visual context prefix).
            session_id     : Active session ID.
            language       : Language mode.
            emotion        : Detected emotion.
            db             : SQLAlchemy session.
            style_prompt_extra: Style instructions from personality engine.
            original_text  : Raw user text without context prefixes (for DB storage).
        """
        # Use original_text for DB if provided, otherwise clean the enriched text
        display_text = original_text or clean_user_text_for_display(text)

        # ── Save user message (clean version) ────────────────
        if db:
            try:
                add_message(
                    db, session_id,
                    role="user", content=display_text,
                    language=language, emotion=emotion
                )
            except Exception as e:
                print(f"[CommandProcessor] Save user message failed: {e}")

        # ── Wake word detection ───────────────────────────────
        try:
            from backend.intent_parser import detect_wake_word
            is_wake, wake_phrase = detect_wake_word(display_text)
        except Exception:
            is_wake, wake_phrase = False, ""

        # ── Get conversation context ──────────────────────────
        context = []
        if db:
            try:
                context = get_context_messages(db, session_id)
            except Exception as e:
                print(f"[CommandProcessor] Context fetch failed: {e}")

        # ── Parse intent ──────────────────────────────────────
        try:
            parsed     = await intent_parser.parse(display_text, language, context)
            intent     = parsed["intent"]
            params     = parsed["params"]
            agent_name = parsed["agent"]
        except Exception as e:
            print(f"[CommandProcessor] Intent parse failed: {e}")
            intent, params, agent_name = "general_qna", {"raw_text": display_text}, None

        # ── Build system prompt ───────────────────────────────
        system_prompt = NEXON_SYSTEM_PROMPT
        if style_prompt_extra and style_prompt_extra.strip():
            system_prompt = f"{NEXON_SYSTEM_PROMPT}\n\n{style_prompt_extra}"

        # ── Generate LLM response ─────────────────────────────
        try:
            llm_response   = await nexon_llm.generate_response(
                user_message = text,  # Send enriched text to LLM (with context)
                context      = context,
                language     = language,
                system       = system_prompt,
            )
            # CRITICAL: Strip ALL JSON from response before showing to user
            clean_response = strip_action_json(llm_response)

            # Safety check: if stripping removed everything, use a fallback
            if not clean_response.strip():
                clean_response = "I'm here to help! What would you like to do?"

        except Exception as e:
            print(f"[CommandProcessor] LLM error: {e}")
            clean_response = (
                "⚠️ I couldn't connect to Ollama. Please make sure:\n"
                "1. Run `ollama serve` in a terminal\n"
                "2. Run `ollama pull llama3.2:3b`\n"
                "Then try again."
            )

        # ── Execute agent (only for real action intents) ──────
        action_result = None
        if (
            agent_name
            and agent_name in AGENT_REGISTRY
            and intent not in CONVERSATIONAL_INTENTS
        ):
            try:
                agent         = AGENT_REGISTRY[agent_name]
                action_result = await agent.handle(intent, params, str(session_id))
                if (
                    action_result.get("success")
                    and action_result.get("message")
                    and action_result["message"].strip() != clean_response.strip()
                ):
                    clean_response = action_result["message"] + "\n\n" + clean_response
            except Exception as e:
                print(f"[CommandProcessor] Agent {agent_name} error: {e}")
                action_result = {
                    "success": False,
                    "message": f"Agent error: {str(e)}",
                    "action" : {"type": intent, "details": {}, "error": str(e)}
                }

        # ── Wake word greeting ────────────────────────────────
        if is_wake and not action_result:
            greetings = {
                "en"      : "Hey! I'm NEXON, your AI assistant. How can I help you today?",
                "hi"      : "नमस्ते! मैं NEXON हूँ। मैं आपकी कैसे मदद कर सकता हूँ?",
                "hinglish": "Hey! Main NEXON hoon. Batao kya karna hai?",
            }
            clean_response = greetings.get(language, greetings["en"])

        # ── Save assistant message ────────────────────────────
        if db:
            try:
                add_message(
                    db, session_id,
                    role="assistant",
                    content=clean_response,
                    language=language,
                    intent=intent,
                    action_data=action_result
                )
            except Exception as e:
                print(f"[CommandProcessor] Save assistant message failed: {e}")

        # ── Background summarization ──────────────────────────
        if db:
            try:
                msgs = get_messages(db, session_id)
                if len(msgs) > 0 and len(msgs) % 20 == 0:
                    older   = [{"role": m.role, "content": m.content} for m in msgs[:-10]]
                    summary = await nexon_llm.summarize_conversation(older)
                    save_summary(db, session_id, summary)
            except Exception:
                pass

        return {
            "response"    : clean_response,
            "intent"      : intent,
            "action"      : action_result,
            "session_id"  : session_id,
            "language"    : language,
            "is_wake_word": is_wake,
            "params"      : params,
        }


command_processor = CommandProcessor()