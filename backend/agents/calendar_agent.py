# backend/agents/calendar_agent.py
# ============================================================
# NEXON Calendar Agent
# Handles calendar event creation, listing, deletion.
# Uses a local JSON store (can be swapped for Google Calendar API).
# ============================================================

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from backend.config import NEXON_HOME
from backend.llm_engine import nexon_llm

CALENDAR_FILE = os.path.join(NEXON_HOME, "calendar.json")


def _load_events() -> List[Dict]:
    """Load events from local JSON calendar file."""
    if os.path.exists(CALENDAR_FILE):
        with open(CALENDAR_FILE, "r") as f:
            return json.load(f)
    return []


def _save_events(events: List[Dict]):
    """Persist events to local JSON calendar file."""
    with open(CALENDAR_FILE, "w") as f:
        json.dump(events, f, indent=2, default=str)


class CalendarAgent:
    """
    Calendar management agent for NEXON.

    Capabilities:
    - Create, list, update, delete calendar events.
    - Generate meeting agendas using LLM.
    - Detect scheduling conflicts.
    - Suggest optimal meeting times.
    - Generate post-meeting summaries.

    Storage: Local JSON file at ~/NEXON/calendar.json.
    Swap _load_events / _save_events for Google Calendar API integration.
    """

    async def handle(self, intent: str, params: Dict, session_id: str) -> Dict:
        """Route calendar intents to the appropriate handler."""
        handlers = {
            "create_calendar_event": self.create_event,
            "list_events"          : self.list_events,
            "delete_event"         : self.delete_event,
            "meeting_summary"      : self.generate_meeting_summary,
        }
        handler = handlers.get(intent, self._unknown)
        return await handler(params, session_id)

    async def create_event(self, params: Dict, session_id: str) -> Dict:
        """
        Create a new calendar event.

        Args:
            params: {
                title       (str): Event title/name.
                date        (str): Date string (e.g., 'tomorrow', '2024-12-25').
                time        (str): Time string (e.g., '3pm', '15:00').
                duration    (int): Duration in minutes (default 60).
                attendees  (list): List of attendee email addresses.
                description (str): Event description.
                location    (str): Event location.
            }
        """
        title       = params.get("title") or params.get("raw_text", "Meeting")[:50]
        date_str    = params.get("date", "today")
        time_str    = params.get("time", "10:00 AM")
        duration    = int(params.get("duration", 60))
        attendees   = params.get("attendees", params.get("all_emails", []))
        description = params.get("description", "")
        location    = params.get("location", "")

        # Parse date
        event_date = self._parse_date(date_str)

        # Check for conflicts
        events    = _load_events()
        conflicts = [
            e for e in events
            if e.get("date") == str(event_date.date()) and e.get("time") == time_str
        ]

        event = {
            "id"         : len(events) + 1,
            "title"      : title,
            "date"       : str(event_date.date()),
            "time"       : time_str,
            "duration"   : duration,
            "attendees"  : attendees,
            "description": description,
            "location"   : location,
            "created_at" : str(datetime.utcnow())
        }

        events.append(event)
        _save_events(events)

        conflict_msg = ""
        if conflicts:
            conflict_msg = f"\n\n⚠️ **Conflict detected** with: {conflicts[0]['title']} at {time_str}"

        attendee_str = ", ".join(attendees) if attendees else "No attendees"

        return {
            "success": True,
            "message": (
                f"✅ Event created!\n\n"
                f"📅 **{title}**\n"
                f"🗓️ {event['date']} at {time_str} ({duration} min)\n"
                f"👥 {attendee_str}"
                f"{conflict_msg}"
            ),
            "action": {
                "type"   : "calendar_event_created",
                "details": event
            }
        }

    async def list_events(self, params: Dict, session_id: str) -> Dict:
        """
        List upcoming calendar events.

        Args:
            params: { days (int): Number of days ahead to look (default 7). }
        """
        events = _load_events()
        days   = int(params.get("days", 7))
        today  = datetime.now().date()
        cutoff = today + timedelta(days=days)

        upcoming = [
            e for e in events
            if today <= datetime.strptime(e["date"], "%Y-%m-%d").date() <= cutoff
        ]

        if not upcoming:
            return {
                "success": True,
                "message": f"📅 No events in the next {days} days. Your schedule is clear!",
                "action": {"type": "list_events", "details": {"events": []}}
            }

        lines = [f"📅 **Upcoming events (next {days} days):**\n"]
        for e in sorted(upcoming, key=lambda x: (x["date"], x["time"])):
            lines.append(f"• **{e['title']}** — {e['date']} at {e['time']} ({e['duration']}min)")

        return {
            "success": True,
            "message": "\n".join(lines),
            "action": {"type": "list_events", "details": {"events": upcoming}}
        }

    async def delete_event(self, params: Dict, session_id: str) -> Dict:
        """
        Delete a calendar event by ID or title.

        Args:
            params: { event_id (int) OR title (str) }
        """
        events    = _load_events()
        event_id  = params.get("event_id")
        title     = params.get("title", "")

        original_count = len(events)
        if event_id:
            events = [e for e in events if e.get("id") != int(event_id)]
        elif title:
            events = [e for e in events if title.lower() not in e.get("title", "").lower()]

        if len(events) < original_count:
            _save_events(events)
            return {
                "success": True,
                "message": "🗑️ Event deleted successfully.",
                "action": {"type": "calendar_event_deleted", "details": {}}
            }
        return {
            "success": False,
            "message": "Could not find that event to delete.",
            "action": {"type": "calendar_event_deleted", "details": {}}
        }

    async def generate_meeting_summary(self, params: Dict, session_id: str) -> Dict:
        """
        Generate a meeting summary with action items using LLM.

        Args:
            params: { transcript (str): Meeting transcript or notes. }
        """
        transcript = params.get("transcript") or params.get("raw_text", "")
        prompt = (
            f"Generate a structured meeting summary from this transcript. "
            f"Include: Key decisions, Action items (with owners), Next steps.\n\n"
            f"Transcript:\n{transcript}"
        )
        summary = await nexon_llm.generate_response(prompt, language="en")
        return {
            "success": True,
            "message": f"📝 **Meeting Summary:**\n\n{summary}",
            "action": {"type": "meeting_summary", "details": {"summary": summary}}
        }

    def _parse_date(self, date_str: str) -> datetime:
        """Parse natural language date strings into datetime objects."""
        date_str = date_str.lower().strip()
        today    = datetime.now()
        days_map = {
            "today": 0, "tomorrow": 1, "yesterday": -1,
            "monday": 0, "tuesday": 1, "wednesday": 2,
            "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
        }
        if date_str in days_map:
            if date_str in ("today", "tomorrow", "yesterday"):
                return today + timedelta(days=days_map[date_str])
            else:
                # Next occurrence of that weekday
                target  = days_map[date_str]
                current = today.weekday()
                delta   = (target - current) % 7 or 7
                return today + timedelta(days=delta)
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            pass
        try:
            return datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            return today

    async def _unknown(self, params: Dict, session_id: str) -> Dict:
        return {
            "success": False,
            "message": "Unknown calendar action.",
            "action": {"type": "unknown", "details": {}}
        }