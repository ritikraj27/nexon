# backend/agents/parallel_executor.py
# ============================================================
# NEXON Parallel Multi-Agent Executor
# Runs multiple agents simultaneously for compound commands.
#
# Example:
#   "Send email to John, book a meeting tomorrow, and take a screenshot"
#   → All 3 agents run in parallel via asyncio.gather()
#   → Live status streamed via WebSocket
# ============================================================

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Callable

from backend.intent_parser import intent_parser
from backend.llm_engine import nexon_llm


class TaskStatus:
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class ParallelTask:
    """Represents a single agent task in a parallel execution batch."""

    def __init__(self, task_id: str, intent: str, params: Dict, agent):
        self.task_id   = task_id
        self.intent    = intent
        self.params    = params
        self.agent     = agent
        self.status    = TaskStatus.PENDING
        self.result    : Optional[Dict] = None
        self.error     : Optional[str]  = None
        self.started_at: Optional[datetime] = None
        self.ended_at  : Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            "task_id"   : self.task_id,
            "intent"    : self.intent,
            "status"    : self.status,
            "result"    : self.result,
            "error"     : self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at"  : self.ended_at.isoformat()   if self.ended_at   else None,
            "duration_ms": (
                int((self.ended_at - self.started_at).total_seconds() * 1000)
                if self.started_at and self.ended_at else None
            ),
        }


class ParallelExecutor:
    """
    Executes multiple NEXON agent tasks concurrently.

    Features:
    - Detects compound intents (multiple actions in one sentence)
    - Runs all sub-tasks via asyncio.gather()
    - Streams live status updates via callback
    - Aggregates results into unified response
    - Handles partial failures gracefully

    Usage:
        executor = ParallelExecutor(agent_registry)
        result = await executor.execute_compound(
            text="Send email to John and take a screenshot",
            session_id=1,
            on_status_update=ws_send
        )
    """

    def __init__(self, agent_registry: Dict):
        self.agents = agent_registry

    async def detect_compound_intents(self, text: str, language: str = "en") -> List[Dict]:
        """
        Detect if a user message contains multiple actionable intents.

        Args:
            text     : User input.
            language : Language mode.
        Returns:
            List of intent dicts, each with 'intent' and 'params'.
        """
        prompt = f"""
Analyze this command and extract ALL separate action intents.
Return ONLY a JSON array. Each item: {{"intent": "...", "params": {{...}}}}
Extract as many distinct intents as present.
If only one intent, return array with one item.

Command: "{text}"

Intent types: send_email, create_calendar_event, create_file, take_screenshot,
open_app, web_scrape, web_search, send_message, set_reminder, process_data,
system_control, note, time_track

Return raw JSON only.
"""
        try:
            raw = await nexon_llm.generate_response(prompt, language="en", max_tokens=400)
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            intents = json.loads(raw)
            if isinstance(intents, list) and len(intents) > 0:
                return intents
        except Exception:
            pass

        # Fallback: single intent detection
        single = await intent_parser.parse(text, language)
        return [{"intent": single["intent"], "params": single["params"]}]

    async def execute_compound(
        self,
        text      : str,
        session_id: int,
        language  : str = "en",
        on_status_update: Optional[Callable] = None,
    ) -> Dict:
        """
        Main entry point for parallel execution.

        Args:
            text             : Full user command.
            session_id       : Active session ID.
            language         : Language mode.
            on_status_update : Async callback for live status (e.g., WebSocket send).
        Returns:
            {
                tasks        : List of task results,
                summary      : Human-readable summary,
                success_count: int,
                fail_count   : int,
                total_ms     : int
            }
        """
        start_time = datetime.utcnow()

        # Detect all intents
        intents = await self.detect_compound_intents(text, language)

        if len(intents) <= 1:
            # Single intent — use normal processor
            return {"compound": False, "intents": intents}

        # Build task list
        tasks = []
        for i, intent_data in enumerate(intents):
            intent_name = intent_data.get("intent", "unknown")
            params      = intent_data.get("params", {})
            params["raw_text"] = text
            params["language"] = language

            agent = self._resolve_agent(intent_name)
            task  = ParallelTask(
                task_id = f"task_{i+1}",
                intent  = intent_name,
                params  = params,
                agent   = agent,
            )
            tasks.append(task)

        # Notify: tasks created
        if on_status_update:
            await self._safe_notify(on_status_update, {
                "event"  : "tasks_created",
                "tasks"  : [t.to_dict() for t in tasks],
                "count"  : len(tasks),
            })

        # Run all tasks in parallel
        await asyncio.gather(*[
            self._run_task(task, str(session_id), on_status_update)
            for task in tasks
        ])

        # Aggregate results
        elapsed_ms    = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        success_tasks = [t for t in tasks if t.status == TaskStatus.SUCCESS]
        failed_tasks  = [t for t in tasks if t.status == TaskStatus.FAILED]

        # Build unified summary
        summary = await self._build_summary(tasks, language)

        result = {
            "compound"     : True,
            "tasks"        : [t.to_dict() for t in tasks],
            "summary"      : summary,
            "success_count": len(success_tasks),
            "fail_count"   : len(failed_tasks),
            "total_ms"     : elapsed_ms,
        }

        # Final notification
        if on_status_update:
            await self._safe_notify(on_status_update, {
                "event"  : "all_done",
                "result" : result,
            })

        return result

    async def _run_task(
        self,
        task: ParallelTask,
        session_id: str,
        on_status_update: Optional[Callable]
    ):
        """Execute a single task with status notifications."""
        task.status     = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()

        if on_status_update:
            await self._safe_notify(on_status_update, {
                "event"  : "task_started",
                "task_id": task.task_id,
                "intent" : task.intent,
            })

        try:
            if task.agent:
                result = await task.agent.handle(task.intent, task.params, session_id)
            else:
                result = {
                    "success": False,
                    "message": f"No agent found for intent: {task.intent}",
                    "action" : {}
                }

            task.result  = result
            task.status  = TaskStatus.SUCCESS if result.get("success", False) else TaskStatus.FAILED
            task.error   = result.get("message") if not result.get("success") else None

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error  = str(e)
            task.result = {"success": False, "message": str(e), "action": {}}

        task.ended_at = datetime.utcnow()

        if on_status_update:
            await self._safe_notify(on_status_update, {
                "event"  : "task_done",
                "task"   : task.to_dict(),
            })

    def _resolve_agent(self, intent: str) -> Optional[object]:
        """Map intent name to agent instance."""
        intent_to_agent = {
            "send_email"            : "EmailAgent",
            "read_email"            : "EmailAgent",
            "reply_email"           : "EmailAgent",
            "create_calendar_event" : "CalendarAgent",
            "list_events"           : "CalendarAgent",
            "create_file"           : "FileAgent",
            "convert_file"          : "FileAgent",
            "summarize_document"    : "FileAgent",
            "take_screenshot"       : "ScreenAgent",
            "open_app"              : "ScreenAgent",
            "system_control"        : "ScreenAgent",
            "web_scrape"            : "WebAgent",
            "web_search"            : "WebAgent",
            "process_data"          : "DataAgent",
            "send_message"          : "MessagingAgent",
            "set_reminder"          : "ProductivityAgent",
            "note"                  : "ProductivityAgent",
            "finance"               : "FinanceAgent",
            "smart_home"            : "SmartHomeAgent",
        }
        agent_name = intent_to_agent.get(intent)
        return self.agents.get(agent_name)

    async def _build_summary(self, tasks: List[ParallelTask], language: str) -> str:
        """Generate a human-readable summary of all task results."""
        lines = []
        for task in tasks:
            icon    = "✅" if task.status == TaskStatus.SUCCESS else "❌"
            intent  = task.intent.replace("_", " ")
            message = ""
            if task.result:
                message = task.result.get("message", "")[:80]
            lines.append(f"{icon} **{intent}**: {message}")

        summary_text = "\n".join(lines)
        duration     = sum(
            t.to_dict().get("duration_ms") or 0 for t in tasks
        )

        return (
            f"⚡ **Parallel execution complete** ({len(tasks)} tasks, {duration}ms)\n\n"
            + summary_text
        )

    async def _safe_notify(self, callback: Callable, data: Dict):
        """Safely call the status update callback."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
        except Exception:
            pass


# ── Gesture Macro Engine ─────────────────────────────────────

class GestureMacroEngine:
    """
    Records and plays back gesture-triggered action sequences.

    Users can define: gesture → list of NEXON commands.
    Example: thumbs_up → send daily standup email

    Macros stored in SQLite via MacroRecord model.
    """

    def __init__(self, db, parallel_executor: ParallelExecutor):
        self.db       = db
        self.executor = parallel_executor
        self._recording: Optional[Dict] = None

    def start_recording(self, gesture_name: str, macro_name: str) -> Dict:
        """Begin recording a new gesture macro."""
        self._recording = {
            "gesture_name": gesture_name,
            "macro_name"  : macro_name,
            "commands"    : [],
            "started_at"  : datetime.utcnow().isoformat(),
        }
        return {"status": "recording", "gesture": gesture_name}

    def add_command(self, command_text: str) -> Dict:
        """Add a command to the current recording."""
        if not self._recording:
            return {"status": "error", "message": "Not recording"}
        self._recording["commands"].append(command_text)
        return {"status": "added", "command": command_text, "total": len(self._recording["commands"])}

    def stop_recording(self) -> Dict:
        """Finish recording and save the macro."""
        if not self._recording:
            return {"status": "error", "message": "Not recording"}

        from backend.db.models import GestureMacro
        macro = GestureMacro(
            gesture_name= self._recording["gesture_name"],
            macro_name  = self._recording["macro_name"],
            commands    = json.dumps(self._recording["commands"]),
            created_at  = datetime.utcnow(),
            run_count   = 0,
        )
        self.db.add(macro)
        self.db.commit()

        result = {
            "status"  : "saved",
            "macro_id": macro.id,
            "name"    : macro.macro_name,
            "commands": self._recording["commands"],
        }
        self._recording = None
        return result

    async def trigger_gesture(
        self, gesture_name: str, session_id: int, language: str = "en"
    ) -> Optional[Dict]:
        """
        Check if a gesture has a macro and execute it if so.

        Args:
            gesture_name : Detected gesture (e.g., 'THUMBS UP').
            session_id   : Current session.
        Returns:
            Execution result if macro found, None otherwise.
        """
        from backend.db.models import GestureMacro
        macro = (
            self.db.query(GestureMacro)
            .filter(GestureMacro.gesture_name == gesture_name.upper())
            .first()
        )
        if not macro:
            return None

        commands = json.loads(macro.commands or "[]")
        if not commands:
            return None

        macro.run_count  = (macro.run_count or 0) + 1
        macro.last_run   = datetime.utcnow()
        self.db.commit()

        # Execute all commands in the macro
        results = []
        for cmd in commands:
            result = await self.executor.execute_compound(cmd, session_id, language)
            results.append(result)

        return {
            "macro_name": macro.macro_name,
            "gesture"   : gesture_name,
            "commands"  : commands,
            "results"   : results,
        }

    def list_macros(self) -> List[Dict]:
        """List all saved gesture macros."""
        from backend.db.models import GestureMacro
        macros = self.db.query(GestureMacro).all()
        return [
            {
                "id"          : m.id,
                "gesture_name": m.gesture_name,
                "macro_name"  : m.macro_name,
                "commands"    : json.loads(m.commands or "[]"),
                "run_count"   : m.run_count,
                "last_run"    : m.last_run.isoformat() if m.last_run else None,
            }
            for m in macros
        ]

    def delete_macro(self, macro_id: int) -> bool:
        """Delete a gesture macro by ID."""
        from backend.db.models import GestureMacro
        macro = self.db.query(GestureMacro).filter(GestureMacro.id == macro_id).first()
        if macro:
            self.db.delete(macro)
            self.db.commit()
            return True
        return False