# backend/personality/style_engine.py
# ============================================================
# NEXON Personality Learning Engine
# Learns the user's communication style over time and adapts
# all AI responses to match their preferences.
#
# Learns:
#   - Preferred response length (short/medium/detailed)
#   - Tone (formal/casual/technical/friendly)
#   - Vocabulary level
#   - Emoji usage preference
#   - Language mix ratio (for Hinglish)
#   - Topics of interest
#   - Time-of-day tone shifts
# ============================================================

import json
import re
from datetime import datetime
from typing import Dict, List, Optional
from collections import Counter
from sqlalchemy.orm import Session as DBSession

from backend.db.models import PersonalityProfile
from backend.llm_engine import nexon_llm


# ── Default personality profile ──────────────────────────────

DEFAULT_PROFILE = {
    "tone"             : "friendly",       # formal | casual | technical | friendly
    "response_length"  : "medium",         # short | medium | detailed
    "emoji_frequency"  : "moderate",       # none | low | moderate | high
    "vocabulary_level" : "general",        # simple | general | technical | expert
    "preferred_language": "en",            # en | hi | hinglish
    "topics_of_interest": [],              # auto-detected from conversations
    "avg_message_length": 0,               # chars — learned from user messages
    "formality_score"  : 0.5,             # 0=very casual, 1=very formal
    "directness_score" : 0.5,             # 0=indirect, 1=direct
    "curiosity_score"  : 0.5,             # how often user asks questions
    "interaction_count": 0,               # total messages processed
    "last_updated"     : None,
    "style_sample"     : "",              # short sample of user's writing style
}


class PersonalityStyleEngine:
    """
    Learns user communication style and shapes AI responses accordingly.

    The engine:
    1. Analyzes every user message to update style profile
    2. Generates system prompt additions that steer the LLM tone
    3. Post-processes responses to match learned preferences

    All profiles stored per-user in SQLite (PersonalityProfile table).
    Multiple users = multiple profiles (identified by user_id).
    """

    def __init__(self, db: DBSession):
        self.db = db

    # ──────────────────────────────────────────
    # PROFILE MANAGEMENT
    # ──────────────────────────────────────────

    def get_profile(self, user_id: str = "default") -> Dict:
        """
        Get the personality profile for a user.

        Args:
            user_id : User identifier (default = 'default').
        Returns:
            Profile dict with all style attributes.
        """
        record = (
            self.db.query(PersonalityProfile)
            .filter(PersonalityProfile.user_id == user_id)
            .first()
        )
        if not record:
            return dict(DEFAULT_PROFILE)

        try:
            return json.loads(record.profile_json)
        except Exception:
            return dict(DEFAULT_PROFILE)

    def _save_profile(self, user_id: str, profile: Dict):
        """Persist profile to database."""
        record = (
            self.db.query(PersonalityProfile)
            .filter(PersonalityProfile.user_id == user_id)
            .first()
        )
        profile["last_updated"] = datetime.utcnow().isoformat()

        if record:
            record.profile_json = json.dumps(profile)
            record.updated_at   = datetime.utcnow()
        else:
            record = PersonalityProfile(
                user_id      = user_id,
                profile_json = json.dumps(profile),
                created_at   = datetime.utcnow(),
                updated_at   = datetime.utcnow(),
            )
            self.db.add(record)

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

    # ──────────────────────────────────────────
    # LEARNING
    # ──────────────────────────────────────────

    def learn_from_message(
        self,
        message : str,
        user_id : str = "default",
        emotion : str = "neutral",
        language: str = "en",
    ) -> Dict:
        """
        Analyze a user message and update the personality profile.

        Call this on every user message — it's fast and lightweight.

        Args:
            message : Raw user message text.
            user_id : User identifier.
            emotion : Detected emotion at time of message.
            language: Active language mode.
        Returns:
            Updated profile dict.
        """
        profile = self.get_profile(user_id)
        profile["interaction_count"] = profile.get("interaction_count", 0) + 1
        count = profile["interaction_count"]

        # ── Message length preference ────────────────────────
        msg_len = len(message)
        old_avg = profile.get("avg_message_length", 0)
        # Exponential moving average
        alpha = 0.1
        profile["avg_message_length"] = int(old_avg * (1 - alpha) + msg_len * alpha)

        # ── Formality detection ──────────────────────────────
        formal_signals   = len(re.findall(
            r'\b(please|kindly|would you|could you|I would like|I am|Dear|Sir|Madam|regards)\b',
            message, re.IGNORECASE
        ))
        casual_signals   = len(re.findall(
            r'\b(hey|hi|yo|gonna|wanna|lol|haha|cool|ok|yeah|nah|btw|idk|omg)\b',
            message, re.IGNORECASE
        ))
        total_signals    = formal_signals + casual_signals + 1
        formality_sample = formal_signals / total_signals
        profile["formality_score"] = (
            profile.get("formality_score", 0.5) * 0.9 + formality_sample * 0.1
        )

        # ── Directness detection ─────────────────────────────
        # Questions = less direct, commands = more direct
        has_question = "?" in message
        is_command   = bool(re.match(r'^(send|create|open|take|find|show|get|run|do|make)\b', message, re.I))
        directness   = 0.8 if is_command else (0.3 if has_question else 0.5)
        profile["directness_score"] = profile.get("directness_score", 0.5) * 0.9 + directness * 0.1

        # ── Curiosity score ──────────────────────────────────
        question_ratio = message.count("?") / max(len(message.split()), 1)
        profile["curiosity_score"] = profile.get("curiosity_score", 0.5) * 0.9 + min(1, question_ratio * 5) * 0.1

        # ── Emoji usage ──────────────────────────────────────
        emoji_count = len(re.findall(r'[\U0001F300-\U0001FFFF]', message))
        if emoji_count > 2:
            profile["emoji_frequency"] = "high"
        elif emoji_count > 0 and count > 5:
            profile["emoji_frequency"] = "moderate"
        elif count > 10 and profile.get("emoji_frequency") != "high":
            profile["emoji_frequency"] = "low"

        # ── Derive tone from formality + directness ──────────
        f = profile["formality_score"]
        d = profile["directness_score"]
        if f > 0.6:
            profile["tone"] = "formal"
        elif f < 0.3 and d > 0.6:
            profile["tone"] = "casual"
        elif d < 0.4:
            profile["tone"] = "friendly"
        else:
            profile["tone"] = "balanced"

        # ── Response length preference ────────────────────────
        avg_len = profile["avg_message_length"]
        if avg_len < 30:
            profile["response_length"] = "short"
        elif avg_len < 100:
            profile["response_length"] = "medium"
        else:
            profile["response_length"] = "detailed"

        # ── Vocabulary level ─────────────────────────────────
        words        = message.lower().split()
        avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
        technical    = len(re.findall(r'\b(api|server|database|algorithm|function|deploy|async|config|json|http)\b', message, re.I))
        if technical > 1:
            profile["vocabulary_level"] = "technical"
        elif avg_word_len > 6:
            profile["vocabulary_level"] = "expert"
        elif avg_word_len > 4.5:
            profile["vocabulary_level"] = "general"
        else:
            profile["vocabulary_level"] = "simple"

        # ── Language preference ───────────────────────────────
        profile["preferred_language"] = language

        # ── Style sample (keep last 200 chars of user text) ──
        if len(message) > 20:
            profile["style_sample"] = message[:200]

        # ── Save updated profile ──────────────────────────────
        self._save_profile(user_id, profile)
        return profile

    async def learn_from_feedback(
        self,
        ai_response    : str,
        user_followup  : str,
        session_id     : int,
        user_id        : str = "default",
    ):
        """
        Detect implicit feedback from user follow-up messages.
        If user says 'be shorter', 'more formal', 'stop using emojis' etc.,
        update profile accordingly.

        Args:
            ai_response  : What NEXON said.
            user_followup: User's next message.
            session_id   : Current session.
            user_id      : User identifier.
        """
        feedback_signals = {
            "shorter"      : ("response_length", "short"),
            "brief"        : ("response_length", "short"),
            "more detail"  : ("response_length", "detailed"),
            "explain more" : ("response_length", "detailed"),
            "simpler"      : ("vocabulary_level", "simple"),
            "technical"    : ("vocabulary_level", "technical"),
            "formal"       : ("tone", "formal"),
            "casual"       : ("tone", "casual"),
            "no emoji"     : ("emoji_frequency", "none"),
            "stop emoji"   : ("emoji_frequency", "none"),
            "more emoji"   : ("emoji_frequency", "high"),
        }

        msg_lower = user_followup.lower()
        profile   = self.get_profile(user_id)
        changed   = False

        for signal, (key, value) in feedback_signals.items():
            if signal in msg_lower:
                profile[key] = value
                changed = True

        if changed:
            self._save_profile(user_id, profile)

    # ──────────────────────────────────────────
    # STYLE INJECTION
    # ──────────────────────────────────────────

    def get_style_prompt_injection(self, user_id: str = "default") -> str:
        """
        Generate a system prompt addition that steers the LLM
        to match the user's learned style preferences.

        Args:
            user_id : User identifier.
        Returns:
            String to append to system prompt (can be empty).
        """
        profile = self.get_profile(user_id)

        if profile.get("interaction_count", 0) < 3:
            return ""  # Not enough data yet

        parts = ["\n[User Style Preferences — adapt your response accordingly:]"]

        # Tone
        tone = profile.get("tone", "friendly")
        tone_instructions = {
            "formal"  : "Use professional, formal language. Avoid contractions and slang.",
            "casual"  : "Use casual, conversational language. Contractions and informal phrases are fine.",
            "friendly": "Be warm and approachable. Use encouraging language.",
            "balanced": "Balance professionalism with approachability.",
        }
        parts.append(f"- Tone: {tone_instructions.get(tone, '')}")

        # Length
        length = profile.get("response_length", "medium")
        length_instructions = {
            "short"   : "Keep responses concise — 1-3 sentences maximum unless detail is essential.",
            "medium"  : "Provide balanced responses — enough detail without being verbose.",
            "detailed": "Provide comprehensive, thorough explanations. The user values depth.",
        }
        parts.append(f"- Length: {length_instructions.get(length, '')}")

        # Vocabulary
        vocab = profile.get("vocabulary_level", "general")
        vocab_instructions = {
            "simple"  : "Use simple, everyday words. Avoid jargon.",
            "general" : "Use clear, accessible language.",
            "technical": "Technical terms are welcome — the user is tech-savvy.",
            "expert"  : "Use advanced vocabulary. No need to over-explain concepts.",
        }
        parts.append(f"- Vocabulary: {vocab_instructions.get(vocab, '')}")

        # Emoji
        emoji = profile.get("emoji_frequency", "moderate")
        if emoji == "none":
            parts.append("- Do NOT use any emojis.")
        elif emoji == "low":
            parts.append("- Use emojis sparingly, only for key points.")
        elif emoji == "high":
            parts.append("- Emojis are welcome and encouraged.")

        # Directness
        directness = profile.get("directness_score", 0.5)
        if directness > 0.7:
            parts.append("- Be direct and action-oriented. Skip preamble.")
        elif directness < 0.3:
            parts.append("- Be thoughtful and exploratory in explanations.")

        return "\n".join(parts)

    def get_profile_summary(self, user_id: str = "default") -> str:
        """Return a human-readable profile summary for display."""
        p = self.get_profile(user_id)
        count = p.get("interaction_count", 0)
        if count < 3:
            return f"Learning your style... ({count} interactions so far)"

        return (
            f"📊 **Your Communication Style**\n"
            f"• Tone: **{p.get('tone', 'balanced').title()}**\n"
            f"• Preferred length: **{p.get('response_length', 'medium').title()}**\n"
            f"• Vocabulary: **{p.get('vocabulary_level', 'general').title()}**\n"
            f"• Emoji: **{p.get('emoji_frequency', 'moderate').title()}**\n"
            f"• Formality: **{int(p.get('formality_score', 0.5) * 100)}%**\n"
            f"• Directness: **{int(p.get('directness_score', 0.5) * 100)}%**\n"
            f"• Interactions learned from: **{count}**"
        )