# backend/agents/productivity_agent.py
# ============================================================
# NEXON Productivity Agent
# Reminders, notes, tasks, time tracking, news aggregation.
# ============================================================

import os
import json
from datetime import datetime
from typing import Dict, List
from backend.config import NEXON_HOME
from backend.llm_engine import nexon_llm

TASKS_FILE     = os.path.join(NEXON_HOME, "tasks.json")
NOTES_FILE     = os.path.join(NEXON_HOME, "notes.json")
REMINDERS_FILE = os.path.join(NEXON_HOME, "reminders.json")


class ProductivityAgent:
    """
    Personal productivity agent for NEXON.

    Capabilities:
    - Create and manage tasks with priorities.
    - Set one-time and recurring reminders.
    - Voice-to-note dictation and organization.
    - Time tracking per project.
    - News aggregation via RSS.
    - Integration stubs for Todoist, Trello, Asana.
    """

    async def handle(self, intent: str, params: Dict, session_id: str) -> Dict:
        handlers = {
            "set_reminder"  : self.set_reminder,
            "note"          : self.create_note,
            "time_track"    : self.time_track,
            "general_qna"   : self.general_qna,
            "small_talk"    : self.small_talk,
        }
        handler = handlers.get(intent, self.general_qna)
        return await handler(params, session_id)

    # ── Reminders ──────────────────────────────
    def _load_json(self, path: str) -> List:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
        return []

    def _save_json(self, path: str, data):
        with open(path, "w") as f: json.dump(data, f, indent=2, default=str)

    async def set_reminder(self, params: Dict, session_id: str) -> Dict:
        """
        Set a reminder.

        Args:
            params: {
                message   (str): What to remind about.
                date      (str): Reminder date.
                time      (str): Reminder time.
                repeat    (str): 'daily'|'weekly'|'monthly'|None.
            }
        """
        message = params.get("message") or params.get("raw_text", "")
        date    = params.get("date", str(datetime.now().date()))
        time_   = params.get("time", "09:00")
        repeat  = params.get("repeat", None)

        reminders = self._load_json(REMINDERS_FILE)
        reminder  = {
            "id"      : len(reminders) + 1,
            "message" : message[:200],
            "date"    : date,
            "time"    : time_,
            "repeat"  : repeat,
            "done"    : False,
            "created" : str(datetime.utcnow())
        }
        reminders.append(reminder)
        self._save_json(REMINDERS_FILE, reminders)

        repeat_str = f" (repeats {repeat})" if repeat else ""
        return {
            "success": True,
            "message": f"⏰ Reminder set!\n**{message[:80]}**\n📅 {date} at {time_}{repeat_str}",
            "action" : {"type": "reminder_set", "details": reminder}
        }

    # ── Notes ──────────────────────────────────

    async def create_note(self, params: Dict, session_id: str) -> Dict:
        """
        Create a structured note.

        Args:
            params: {
                title    (str): Note title.
                content  (str): Note body.
                tags     (list): Tags for categorization.
                raw_text (str): Full user request.
            }
        """
        title   = params.get("title", f"Note {datetime.now().strftime('%Y%m%d_%H%M')}")
        content = params.get("content") or params.get("raw_text", "")
        tags    = params.get("tags", [])

        notes = self._load_json(NOTES_FILE)
        note  = {
            "id"      : len(notes) + 1,
            "title"   : title,
            "content" : content,
            "tags"    : tags,
            "created" : str(datetime.utcnow())
        }
        notes.append(note)
        self._save_json(NOTES_FILE, notes)

        # Also save as markdown file
        note_path = os.path.join(NEXON_HOME, "Notes", f"{title}.md")
        os.makedirs(os.path.dirname(note_path), exist_ok=True)
        with open(note_path, "w") as f:
            f.write(f"# {title}\n\n{content}\n\nTags: {', '.join(tags)}\n")

        return {
            "success": True,
            "message": f"📝 Note saved: **{title}**\n`{note_path}`",
            "action" : {"type": "note_created", "details": note}
        }

    # ── Time Tracking ──────────────────────────

    async def time_track(self, params: Dict, session_id: str) -> Dict:
        """
        Log time spent on a task/project.

        Args:
            params: {
                project  (str)  : Project name.
                duration (float): Duration in minutes.
                action   (str)  : 'log'|'report'.
            }
        """
        project  = params.get("project", "General")
        duration = float(params.get("duration", 0))
        action   = params.get("action", "log")

        time_file = os.path.join(NEXON_HOME, "time_log.json")
        entries   = self._load_json(time_file)

        if action == "report":
            by_proj = {}
            for e in entries:
                proj = e.get("project", "General")
                by_proj[proj] = by_proj.get(proj, 0) + e.get("duration", 0)
            report = "\n".join(
                f"  • **{p}**: {m:.0f} min ({m/60:.1f}h)"
                for p, m in sorted(by_proj.items(), key=lambda x: -x[1])
            ) or "No time logged yet."
            return {
                "success": True,
                "message": f"⏱️ **Time Report:**\n{report}",
                "action" : {"type": "time_report", "details": by_proj}
            }

        if duration <= 0:
            return {"success": False, "message": "Please specify duration in minutes.", "action": {}}

        entry = {
            "project" : project,
            "duration": duration,
            "date"    : str(datetime.now().date()),
            "logged"  : str(datetime.utcnow())
        }
        entries.append(entry)
        self._save_json(time_file, entries)

        return {
            "success": True,
            "message": f"⏱️ Logged **{duration:.0f} minutes** on **{project}**.",
            "action" : {"type": "time_logged", "details": entry}
        }

    # ── General QA / Small Talk ─────────────────

    async def general_qna(self, params: Dict, session_id: str) -> Dict:
        """Fallback: use LLM to answer general questions."""
        return {
            "success": True,
            "message": "",  # Response handled by LLM in command_processor
            "action" : None
        }

    async def small_talk(self, params: Dict, session_id: str) -> Dict:
        """Handle casual conversation."""
        return await self.general_qna(params, session_id)