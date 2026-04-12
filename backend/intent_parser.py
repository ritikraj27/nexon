# backend/intent_parser.py
# ============================================================
# NEXON Intent Parser
# Classifies user input into structured intents with entities.
# Uses LLM for classification + regex for fast entity extraction.
# ============================================================

import re
from typing import Dict, List, Optional, Tuple
from backend.llm_engine import nexon_llm

# ─────────────────────────────────────────────
# Intent categories
# ─────────────────────────────────────────────

INTENT_MAP = {
    # Communication
    "send_email"            : ["email agent", "EmailAgent"],
    "read_email"            : ["email agent", "EmailAgent"],
    "reply_email"           : ["email agent", "EmailAgent"],
    "send_message"          : ["messaging agent", "MessagingAgent"],
    "make_call"             : ["messaging agent", "MessagingAgent"],

    # Calendar
    "create_calendar_event" : ["calendar agent", "CalendarAgent"],
    "list_events"           : ["calendar agent", "CalendarAgent"],
    "delete_event"          : ["calendar agent", "CalendarAgent"],
    "meeting_summary"       : ["calendar agent", "CalendarAgent"],

    # Files
    "create_file"           : ["file agent", "FileAgent"],
    "convert_file"          : ["file agent", "FileAgent"],
    "move_file"             : ["file agent", "FileAgent"],
    "summarize_document"    : ["file agent", "FileAgent"],
    "merge_pdf"             : ["file agent", "FileAgent"],
    "upload_file"           : ["file agent", "FileAgent"],

    # Screen / System
    "take_screenshot"       : ["screen agent", "ScreenAgent"],
    "screen_record"         : ["screen agent", "ScreenAgent"],
    "open_app"              : ["screen agent", "ScreenAgent"],
    "system_control"        : ["screen agent", "ScreenAgent"],
    "clipboard"             : ["screen agent", "ScreenAgent"],

    # Web
    "web_scrape"            : ["web agent", "WebAgent"],
    "web_search"            : ["web agent", "WebAgent"],
    "form_fill"             : ["web agent", "WebAgent"],
    "price_track"           : ["web agent", "WebAgent"],

    # Data
    "process_data"          : ["data agent", "DataAgent"],
    "generate_report"       : ["data agent", "DataAgent"],
    "analyze_data"          : ["data agent", "DataAgent"],

    # Smart home / Finance / Productivity
    "smart_home"            : ["smart home agent", "SmartHomeAgent"],
    "finance"               : ["finance agent", "FinanceAgent"],
    "set_reminder"          : ["productivity agent", "ProductivityAgent"],
    "note"                  : ["productivity agent", "ProductivityAgent"],
    "time_track"            : ["productivity agent", "ProductivityAgent"],

    # General
    "small_talk"            : [None, None],
    "general_qna"           : [None, None],
    "unknown"               : [None, None],
}

# ─────────────────────────────────────────────
# Fast regex-based entity extractors
# ─────────────────────────────────────────────

EMAIL_PATTERN    = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
URL_PATTERN      = re.compile(r"https?://[^\s]+")
TIME_PATTERN     = re.compile(
    r"\b(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?|\d{1,2}\s*(?:am|pm|AM|PM))\b"
)
DATE_PATTERN     = re.compile(
    r"\b(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
    re.IGNORECASE
)
FILE_PATTERN     = re.compile(r"\b[\w\- ]+\.(pdf|docx|txt|csv|xlsx|png|jpg|mp4|py|js)\b", re.IGNORECASE)
APP_PATTERN      = re.compile(
    r"\b(chrome|safari|firefox|vscode|code|slack|zoom|teams|discord|"
    r"spotify|terminal|finder|explorer|notepad|word|excel|powerpoint|"
    r"whatsapp|telegram|gmail|calendar)\b",
    re.IGNORECASE
)
PHONE_PATTERN    = re.compile(r"\b(\+?\d[\d\s\-]{7,}\d)\b")


def extract_entities(text: str) -> Dict:
    """
    Fast regex-based entity extraction from raw text.

    Args:
        text : Raw user input string.
    Returns:
        Dict of extracted entities:
            emails, urls, times, dates, files, apps, phones.
    """
    return {
        "emails" : EMAIL_PATTERN.findall(text),
        "urls"   : URL_PATTERN.findall(text),
        "times"  : TIME_PATTERN.findall(text),
        "dates"  : DATE_PATTERN.findall(text),
        "files"  : FILE_PATTERN.findall(text),
        "apps"   : APP_PATTERN.findall(text),
        "phones" : PHONE_PATTERN.findall(text),
    }


def detect_wake_word(text: str) -> Tuple[bool, str]:
    """
    Check if the text contains a NEXON wake word.

    Args:
        text : Transcribed or typed text.
    Returns:
        Tuple of (is_wake_word: bool, matched_phrase: str).
    """
    from backend.speech.whisper_engine import WAKE_WORDS
    text_lower = text.lower()
    for wake in WAKE_WORDS:
        if wake in text_lower:
            return True, wake
    return False, ""


def detect_language(text: str) -> str:
    """
    Heuristic language detection for en/hi/hinglish.
    Counts Devanagari characters vs Latin characters.

    Args:
        text : Input string.
    Returns:
        'hi' | 'en' | 'hinglish'
    """
    devanagari = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    latin      = sum(1 for c in text if c.isascii() and c.isalpha())
    total      = devanagari + latin

    if total == 0:
        return "en"
    ratio = devanagari / total
    if ratio > 0.6:
        return "hi"
    if ratio > 0.15:
        return "hinglish"
    return "en"


# ─────────────────────────────────────────────
# Main Intent Parser Class
# ─────────────────────────────────────────────

class IntentParser:
    """
    Parses user text into structured intent + entity objects.

    Combines fast rule-based entity extraction with LLM-based
    intent classification for accurate understanding.
    """

    async def parse(
        self,
        text: str,
        language: str = "en",
        context: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Full parse pipeline: entity extraction + intent classification.

        Args:
            text     : Raw user input.
            language : Current language mode.
            context  : Recent conversation messages for context.
        Returns:
            Dict with keys:
                intent   (str)  : Classified intent name.
                params   (dict) : Extracted parameters and entities.
                agent    (str)  : Agent name to handle this intent.
                confidence (float): Classification confidence.
                is_wake_word (bool): Whether wake word was detected.
                detected_language (str): Auto-detected language.
        """
        # Step 1: Fast entity extraction
        entities   = extract_entities(text)
        is_wake, wake_phrase = detect_wake_word(text)
        auto_lang  = detect_language(text)

        # Step 2: LLM intent classification
        llm_result = await nexon_llm.classify_intent(text)
        intent     = llm_result.get("intent", "unknown")
        params     = llm_result.get("params", {})
        confidence = llm_result.get("confidence", 0.5)

        # Step 3: Merge regex entities into params
        if entities["emails"] and "recipient" not in params:
            params["recipient"] = entities["emails"][0]
            params["all_emails"] = entities["emails"]
        if entities["dates"] and "date" not in params:
            params["date"] = entities["dates"][0]
        if entities["times"] and "time" not in params:
            params["time"] = entities["times"][0]
        if entities["files"] and "filename" not in params:
            params["filename"] = entities["files"][0]
        if entities["apps"] and "app_name" not in params:
            params["app_name"] = entities["apps"][0].lower()
        if entities["urls"] and "url" not in params:
            params["url"] = entities["urls"][0]

        params["raw_text"]  = text
        params["language"]  = language or auto_lang
        params["entities"]  = entities

        # Step 4: Resolve agent
        agent_info = INTENT_MAP.get(intent, [None, None])
        agent_name = agent_info[1]  # e.g. "EmailAgent"

        return {
            "intent"           : intent,
            "params"           : params,
            "agent"            : agent_name,
            "confidence"       : confidence,
            "is_wake_word"     : is_wake,
            "wake_word"        : wake_phrase,
            "detected_language": auto_lang,
        }


# Singleton
intent_parser = IntentParser()