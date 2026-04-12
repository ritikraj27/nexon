# backend/predictive/intent_engine.py
# ============================================================
# NEXON Predictive Intent Engine
# Mines usage patterns and proactively suggests next actions.
#
# Examples of what it learns:
#   - "Every Monday 9am → send standup email"
#   - "After creating a file → usually uploads to Drive"
#   - "When emotion=stressed → prefers shorter responses"
#
# Install: pip install apscheduler
# ============================================================

import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import Counter, defaultdict
from sqlalchemy.orm import Session as DBSession

from backend.db.models import UsagePattern, Message, Session


class PredictiveIntentEngine:
    """
    Learns from the user's interaction patterns over time and
    generates proactive suggestions.

    Pattern types tracked:
    - Time-based: "Every Monday at 9am you send a standup"
    - Sequence-based: "After send_email you usually check_calendar"
    - Emotion-based: "When ANGRY, you prefer concise responses"
    - Context-based: "On Monday mornings you open Chrome + Slack"
    """

    def __init__(self, db: DBSession):
        self.db = db

    # ──────────────────────────────────────────
    # PATTERN RECORDING
    # ──────────────────────────────────────────

    def record_action(
        self,
        intent    : str,
        params    : Dict,
        session_id: int,
        emotion   : str = "neutral",
        success   : bool = True,
    ):
        """
        Record a user action for pattern learning.

        Args:
            intent    : The intent that was executed.
            params    : Intent parameters.
            session_id: Session ID.
            emotion   : User emotion at time of action.
            success   : Whether the action succeeded.
        """
        now         = datetime.utcnow()
        day_of_week = now.strftime('%A').lower()   # monday, tuesday…
        hour_of_day = now.hour
        time_slot   = f"{hour_of_day:02d}:00"

        # Time-based pattern key
        time_key = f"time:{day_of_week}:{time_slot}:{intent}"

        # Sequence key (what came before)
        prev_intent = self._get_last_intent(session_id)
        seq_key     = f"seq:{prev_intent}→{intent}" if prev_intent else None

        # Emotion key
        emotion_key = f"emotion:{emotion}:{intent}"

        for key in [time_key, seq_key, emotion_key]:
            if not key:
                continue
            self._increment_pattern(
                key        = key,
                intent     = intent,
                params     = params,
                emotion    = emotion,
                day_of_week= day_of_week,
                hour_of_day= hour_of_day,
                success    = success,
            )

    def _increment_pattern(self, key, intent, params, emotion, day_of_week, hour_of_day, success):
        """Increment or create a pattern record."""
        pattern = self.db.query(UsagePattern).filter(UsagePattern.pattern_key == key).first()
        if pattern:
            pattern.count      += 1
            pattern.last_seen   = datetime.utcnow()
            if success:
                pattern.success_count = (pattern.success_count or 0) + 1
        else:
            pattern = UsagePattern(
                pattern_key   = key,
                intent        = intent,
                params_sample = json.dumps(params)[:500],
                emotion       = emotion,
                day_of_week   = day_of_week,
                hour_of_day   = hour_of_day,
                count         = 1,
                success_count = 1 if success else 0,
                first_seen    = datetime.utcnow(),
                last_seen     = datetime.utcnow(),
            )
            self.db.add(pattern)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _get_last_intent(self, session_id: int) -> Optional[str]:
        """Get the most recent intent from this session."""
        msg = (
            self.db.query(Message)
            .filter(Message.session_id == session_id, Message.role == "assistant",
                    Message.intent != "", Message.intent != None)
            .order_by(Message.id.desc())
            .first()
        )
        return msg.intent if msg else None

    # ──────────────────────────────────────────
    # PREDICTION
    # ──────────────────────────────────────────

    def get_suggestions(
        self,
        current_emotion: str = "neutral",
        top_k          : int = 3,
        min_count      : int = 2,
    ) -> List[Dict]:
        """
        Generate proactive suggestions based on current time + patterns.

        Args:
            current_emotion : Currently detected emotion.
            top_k           : Max suggestions to return.
            min_count       : Minimum pattern occurrences required.
        Returns:
            List of suggestion dicts with text, confidence, intent, params.
        """
        now         = datetime.utcnow()
        day_of_week = now.strftime('%A').lower()
        hour_of_day = now.hour
        time_slot   = f"{hour_of_day:02d}:00"

        suggestions = []

        # 1. Time-based suggestions
        time_patterns = (
            self.db.query(UsagePattern)
            .filter(
                UsagePattern.pattern_key.like(f"time:{day_of_week}:{time_slot}:%"),
                UsagePattern.count >= min_count
            )
            .order_by(UsagePattern.count.desc())
            .limit(5)
            .all()
        )

        for p in time_patterns:
            conf = min(0.95, p.count * 0.15 + (p.success_count or 0) * 0.05)
            suggestions.append({
                "text"      : self._format_suggestion(p, "time", day_of_week, hour_of_day),
                "intent"    : p.intent,
                "params"    : json.loads(p.params_sample or "{}"),
                "confidence": round(conf, 2),
                "type"      : "time",
                "count"     : p.count,
            })

        # 2. Emotion-based suggestions
        if current_emotion != "neutral":
            emotion_patterns = (
                self.db.query(UsagePattern)
                .filter(
                    UsagePattern.pattern_key.like(f"emotion:{current_emotion}:%"),
                    UsagePattern.count >= min_count
                )
                .order_by(UsagePattern.count.desc())
                .limit(3)
                .all()
            )
            for p in emotion_patterns:
                conf = min(0.85, p.count * 0.12)
                suggestions.append({
                    "text"      : f"When you're {current_emotion}, you usually: {p.intent.replace('_', ' ')}",
                    "intent"    : p.intent,
                    "params"    : json.loads(p.params_sample or "{}"),
                    "confidence": round(conf, 2),
                    "type"      : "emotion",
                    "count"     : p.count,
                })

        # Sort by confidence and deduplicate by intent
        seen_intents = set()
        unique = []
        for s in sorted(suggestions, key=lambda x: -x["confidence"]):
            if s["intent"] not in seen_intents:
                seen_intents.add(s["intent"])
                unique.append(s)

        return unique[:top_k]

    def _format_suggestion(self, pattern: "UsagePattern", ptype: str, day: str, hour: int) -> str:
        """Format a human-readable suggestion string."""
        intent_readable = pattern.intent.replace("_", " ").title()
        if ptype == "time":
            period = "morning" if 6 <= hour < 12 else "afternoon" if 12 <= hour < 18 else "evening"
            return f"You usually {intent_readable.lower()} on {day.title()} {period}. Want me to do it now?"
        return f"Suggested: {intent_readable}"

    def get_analytics(self) -> Dict:
        """
        Return usage analytics summary.

        Returns:
            Dict with top intents, busiest times, emotion patterns.
        """
        all_patterns = self.db.query(UsagePattern).all()

        intent_counts = defaultdict(int)
        hour_counts   = defaultdict(int)
        day_counts    = defaultdict(int)
        emotion_counts= defaultdict(int)

        for p in all_patterns:
            intent_counts[p.intent]    += p.count
            hour_counts[p.hour_of_day] += p.count
            day_counts[p.day_of_week]  += p.count
            emotion_counts[p.emotion]  += p.count

        return {
            "top_intents": sorted(intent_counts.items(), key=lambda x: -x[1])[:5],
            "busiest_hour": max(hour_counts, key=hour_counts.get, default=9),
            "busiest_day" : max(day_counts,  key=day_counts.get,  default="monday"),
            "top_emotions": sorted(emotion_counts.items(), key=lambda x: -x[1])[:3],
            "total_actions": sum(p.count for p in all_patterns),
        }

    def get_sequence_completions(self, last_intent: str) -> List[Dict]:
        """
        Given the last intent, predict what the user will do next.

        Args:
            last_intent : The intent just executed.
        Returns:
            List of likely next intents with confidence scores.
        """
        patterns = (
            self.db.query(UsagePattern)
            .filter(UsagePattern.pattern_key.like(f"seq:{last_intent}→%"))
            .order_by(UsagePattern.count.desc())
            .limit(3)
            .all()
        )
        results = []
        for p in patterns:
            next_intent = p.pattern_key.split("→")[-1]
            conf = min(0.9, p.count * 0.2)
            results.append({
                "next_intent": next_intent,
                "text"       : f"Next: {next_intent.replace('_', ' ')}?",
                "confidence" : round(conf, 2),
            })
        return results