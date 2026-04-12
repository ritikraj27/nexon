# backend/agents/finance_agent.py
# ============================================================
# NEXON Finance Agent
# Expense tracking, bill reminders, anomaly detection.
# ============================================================

import os
import json
from datetime import datetime
from typing import Dict, List
from backend.config import NEXON_HOME
from backend.llm_engine import nexon_llm

EXPENSES_FILE = os.path.join(NEXON_HOME, "expenses.json")


class FinanceAgent:
    """
    Personal finance management agent for NEXON.

    Capabilities:
    - Log and categorize expenses.
    - Track bills and set payment reminders.
    - Generate spending reports.
    - Detect unusual spending patterns.
    - Budget monitoring.

    Storage: Local JSON at ~/NEXON/expenses.json.
    """

    async def handle(self, intent: str, params: Dict, session_id: str) -> Dict:
        handlers = {
            "finance"     : self.finance_action,
            "log_expense" : self.log_expense,
            "view_expenses": self.view_expenses,
        }
        handler = handlers.get(intent, self.finance_action)
        return await handler(params, session_id)

    async def finance_action(self, params: Dict, session_id: str) -> Dict:
        """Route finance sub-actions."""
        sub = params.get("sub_action", "view")
        if sub == "log":
            return await self.log_expense(params, session_id)
        elif sub == "report":
            return await self.spending_report(params, session_id)
        else:
            return await self.view_expenses(params, session_id)

    def _load_expenses(self) -> List[Dict]:
        if os.path.exists(EXPENSES_FILE):
            with open(EXPENSES_FILE) as f:
                return json.load(f)
        return []

    def _save_expenses(self, expenses: List[Dict]):
        with open(EXPENSES_FILE, "w") as f:
            json.dump(expenses, f, indent=2, default=str)

    async def log_expense(self, params: Dict, session_id: str) -> Dict:
        """
        Log a new expense entry.

        Args:
            params: {
                amount   (float): Expense amount.
                category (str)  : 'food'|'transport'|'entertainment'|'bills'|'shopping'|'other'.
                description (str): What the expense was for.
                date     (str)  : Date (default: today).
            }
        """
        amount      = float(params.get("amount", 0))
        category    = params.get("category", "other")
        description = params.get("description") or params.get("raw_text", "")
        date        = params.get("date", str(datetime.now().date()))

        if amount <= 0:
            return {"success": False, "message": "Please specify the expense amount.", "action": {}}

        expenses = self._load_expenses()
        entry    = {
            "id"         : len(expenses) + 1,
            "amount"     : amount,
            "category"   : category,
            "description": description[:100],
            "date"       : date,
            "logged_at"  : str(datetime.utcnow())
        }
        expenses.append(entry)
        self._save_expenses(expenses)

        # Simple anomaly check
        recent = [e["amount"] for e in expenses[-10:]]
        avg    = sum(recent) / len(recent) if recent else 0
        alert  = ""
        if amount > avg * 3 and avg > 0:
            alert = f"\n\n⚠️ This expense is **{amount/avg:.1f}x** your recent average — unusual spending detected!"

        return {
            "success": True,
            "message": f"💰 Expense logged!\n**Amount:** ${amount:.2f}\n**Category:** {category}\n**Description:** {description}{alert}",
            "action" : {"type": "expense_logged", "details": entry}
        }

    async def view_expenses(self, params: Dict, session_id: str) -> Dict:
        """View recent expenses with totals by category."""
        expenses = self._load_expenses()
        if not expenses:
            return {"success": True, "message": "No expenses logged yet. Say 'log expense $X for Y' to start.", "action": {}}

        last_10  = expenses[-10:]
        by_cat   = {}
        for e in last_10:
            cat = e.get("category", "other")
            by_cat[cat] = by_cat.get(cat, 0) + e.get("amount", 0)

        total    = sum(e.get("amount", 0) for e in last_10)
        cat_str  = "\n".join(f"  • {k}: ${v:.2f}" for k, v in sorted(by_cat.items(), key=lambda x: -x[1]))
        entry_str = "\n".join(f"  {e['date']} | ${e['amount']:.2f} | {e['category']} — {e['description'][:40]}" for e in reversed(last_10[:5]))

        return {
            "success": True,
            "message": f"💳 **Recent Expenses (last 10)**\n\n**Total:** ${total:.2f}\n\n**By Category:**\n{cat_str}\n\n**Latest:**\n{entry_str}",
            "action" : {"type": "expenses_viewed", "details": {"total": total, "by_category": by_cat}}
        }

    async def spending_report(self, params: Dict, session_id: str) -> Dict:
        """Generate an LLM-powered spending analysis report."""
        expenses = self._load_expenses()
        if not expenses:
            return {"success": False, "message": "No expenses to analyze.", "action": {}}

        data_str = json.dumps(expenses[-30:], indent=2)
        analysis = await nexon_llm.generate_response(
            f"Analyze these expenses and provide: 1) Spending patterns 2) Top categories 3) Money-saving suggestions\n\n{data_str}",
            language="en"
        )
        return {
            "success": True,
            "message": f"📊 **Spending Analysis:**\n\n{analysis}",
            "action" : {"type": "finance_report", "details": {}}
        }