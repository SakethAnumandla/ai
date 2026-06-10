"""Multi-turn delete / update expense workflows (date range → list → pick ID → act)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy.orm import Session

from app.ai.schemas.workflow import (
    ConversationWorkflowState,
    StateMachineResult,
    WorkflowScope,
    WorkflowType,
)
from app.ai.utils.date_range_parser import parse_date_range
from app.ai.workflow.slot_parser import parse_slot_updates
from app.models import Expense
from app.services.expense_service import ExpenseService

ManageAction = Literal["delete", "update"]

_DELETE_START = re.compile(
    r"\b(delete|remove)\b.*\b(expense|expenses|bill|bills|draft)\b|"
    r"\bdelete\s+(?:an?\s+)?expense\b|"
    r"\b(want|wanted|need|like)\s+to\s+(?:delete|remove)\b.*\b(expense|bill)",
    re.IGNORECASE,
)
_UPDATE_START = re.compile(
    r"\b(update|edit|change|modify)\b.*\b(expense|expenses|bill|bills|draft)\b|"
    r"\b(?:update|edit)\s+(?:an?\s+)?expense\b|"
    r"\b(want|wanted|need|like)\s+to\s+(?:update|edit|change)\b.*\b(expense|bill)",
    re.IGNORECASE,
)
_EXPENSE_ID_REF = re.compile(
    r"(?:delete|update|edit|remove|change|modify)\s+(?:expense\s*)?#?(\d+)\b|"
    r"\bexpense\s*#?\s*(\d+)\b|"
    r"^#?(\d+)\s*$",
    re.IGNORECASE,
)


def detect_manage_action(text: str) -> Optional[ManageAction]:
    if not text or not text.strip():
        return None
    if _DELETE_START.search(text):
        return "delete"
    if _UPDATE_START.search(text):
        return "update"
    return None


def parse_expense_field_updates(text: str) -> Dict[str, Any]:
    """Parse amount / vendor / category / date from update messages."""
    updates = dict(parse_slot_updates(text))
    if not (text or "").strip():
        return updates

    amount_m = re.search(
        r"\b(?:amount|bill|total)\s*(?:to|=|:)?\s*(?:₹|rs\.?)?\s*(\d+(?:\.\d+)?)\b",
        text,
        re.IGNORECASE,
    )
    if amount_m:
        updates["bill_amount"] = float(amount_m.group(1))

    vendor_m = re.search(
        r"\b(?:vendor|merchant)\s*(?:to|=|:)?\s*([a-z][a-z0-9\s&'.-]{2,48})",
        text,
        re.IGNORECASE,
    )
    if vendor_m:
        updates["vendor_name"] = vendor_m.group(1).strip().title()

    date_m = re.search(
        r"\b(?:date|bill\s*date)\s*(?:to|=|:)?\s*([0-9]{1,2}[\s/-][a-z0-9\s/-]{4,20}|\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if date_m:
        updates["bill_date"] = date_m.group(1).strip()

    cat_m = re.search(
        r"\b(?:category|main\s*category)\s*(?:to|=|:)?\s*([a-z][a-z0-9\s_-]{2,32})",
        text,
        re.IGNORECASE,
    )
    if cat_m:
        updates["main_category"] = cat_m.group(1).strip().lower().replace(" ", "_")

    return updates


def parse_expense_id_from_message(text: str) -> Optional[int]:
    m = _EXPENSE_ID_REF.search(text.strip())
    if not m:
        return None
    for g in m.groups():
        if g:
            try:
                return int(g)
            except ValueError:
                continue
    return None


def format_expense_list(
    expenses: List[Expense],
    *,
    start: datetime,
    end: datetime,
    action: ManageAction,
) -> str:
    start_s = start.strftime("%d %b %Y")
    end_s = end.strftime("%d %b %Y")
    verb = "delete" if action == "delete" else "update"
    if not expenses:
        return (
            f"No expenses found between **{start_s}** and **{end_s}**. "
            f"Try a wider date range or say **cancel**."
        )

    lines = [
        f"Here are your expenses from **{start_s}** to **{end_s}** ({len(expenses)} shown):\n"
    ]
    for e in expenses:
        vendor = e.vendor_name or "—"
        date_s = e.bill_date.strftime("%d %b %Y") if e.bill_date else "—"
        amt = e.bill_amount or 0
        lines.append(
            f"• **#{e.id}** — {vendor} — ₹{amt:,.2f} — {date_s} — {e.status.value.upper()}"
        )
    lines.append(
        f"\nReply with **{verb} expense <ID>** (e.g. `{verb} expense 33`). "
        "For updates you can add fields: `update expense 33 amount 500` or `vendor Ghiotto`."
    )
    return "\n".join(lines)


class ExpenseManageWorkflow:
    def __init__(self, db: Session):
        self._db = db

    def start(
        self,
        action: ManageAction,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        initial_text: Optional[str] = None,
    ) -> StateMachineResult:
        wf_type = (
            WorkflowType.EXPENSE_DELETE
            if action == "delete"
            else WorkflowType.EXPENSE_UPDATE
        )
        state = ConversationWorkflowState(
            workflow_type=wf_type,
            scope=WorkflowScope.EXPENSE,
            slots={"action": action, "user_id": user_id},
            pending_slots=["date_range"],
            session_id=session_id,
        )
        if initial_text and parse_date_range(initial_text):
            result = self.process_turn(initial_text, state)
            if result.handled:
                return result
        return StateMachineResult(
            handled=True,
            assistant_message=(
                "What **date range** should I search? "
                "(e.g. *last week*, *1 May to 15 May 2024*, *October 2024*)"
            ),
            updated_state=state,
        )

    def process_turn(
        self,
        text: str,
        state: ConversationWorkflowState,
    ) -> StateMachineResult:
        action: ManageAction = state.slots.get("action") or "delete"
        lowered = (text or "").strip().lower()
        if lowered in ("cancel", "stop", "never mind", "abort"):
            return StateMachineResult(
                handled=True,
                assistant_message="Okay, I've cancelled the expense " + action + " flow.",
                clear_state=True,
            )

        if "date_range" in state.pending_slots:
            return self._handle_date_range(text, state, action)

        if "expense_id" in state.pending_slots:
            return self._handle_expense_pick(text, state, action)

        if "changes" in state.pending_slots:
            return self._handle_changes(text, state)

        return StateMachineResult(handled=False)

    def _handle_date_range(
        self,
        text: str,
        state: ConversationWorkflowState,
        action: ManageAction,
    ) -> StateMachineResult:
        parsed = parse_date_range(text)
        if not parsed:
            if detect_manage_action(text) or parse_expense_id_from_message(text):
                return StateMachineResult(
                    handled=True,
                    assistant_message=(
                        "What **date range** should I search? "
                        "(e.g. *last week*, *1 May to 15 May 2024*, *October 2024*)"
                    ),
                    updated_state=state,
                )
            return StateMachineResult(
                handled=True,
                assistant_message=(
                    "I couldn't understand that date range. Try examples like "
                    "**last week**, **this month**, **1 May to 15 May 2024**, or **October 2024**."
                ),
                updated_state=state,
            )

        start, end = parsed
        user_id = state.slots.get("user_id")
        if user_id is None:
            return StateMachineResult(
                handled=True,
                assistant_message="Session error: missing user context. Please try again.",
                clear_state=True,
            )
        svc = ExpenseService(self._db)
        expenses, total = svc.get_user_expenses(
            user_id,
            start_date=start,
            end_date=end,
            limit=50,
        )

        candidate_ids = [e.id for e in expenses]
        state.fill_slot("date_range", text)
        state.slots["start_date"] = start.isoformat()
        state.slots["end_date"] = end.isoformat()
        state.slots["candidate_ids"] = candidate_ids
        state.slots["total_in_range"] = total
        if "date_range" in state.pending_slots:
            state.pending_slots.remove("date_range")
        if candidate_ids:
            state.pending_slots.append("expense_id")
        else:
            state.pending_slots.clear()

        # If user already named an expense in the same message
        eid = parse_expense_id_from_message(text)
        if eid and eid in candidate_ids:
            state.fill_slot("expense_id", eid)
            if "expense_id" in state.pending_slots:
                state.pending_slots.remove("expense_id")
            return self._complete_pick(state, action, eid)

        msg = format_expense_list(expenses, start=start, end=end, action=action)
        if total > len(expenses):
            msg += f"\n\n_Showing {len(expenses)} of {total} — use the expense **#ID** from the list._"
        return StateMachineResult(
            handled=True,
            assistant_message=msg,
            updated_state=state,
        )

    def _handle_expense_pick(
        self,
        text: str,
        state: ConversationWorkflowState,
        action: ManageAction,
    ) -> StateMachineResult:
        eid = parse_expense_id_from_message(text)
        if not eid:
            return StateMachineResult(
                handled=True,
                assistant_message=(
                    "Which expense should I use? Reply with the **ID** from the list, "
                    "e.g. `delete expense 33` or `update expense 21`."
                ),
                updated_state=state,
            )

        candidates = state.slots.get("candidate_ids") or []
        user_id = state.slots.get("user_id")
        if eid not in candidates and user_id:
            svc = ExpenseService(self._db)
            exp = svc.get_expense(eid, user_id)
            if not exp:
                return StateMachineResult(
                    handled=True,
                    assistant_message=f"Expense **#{eid}** was not found. Pick an ID from the list above.",
                    updated_state=state,
                )
            try:
                start = datetime.fromisoformat(state.slots["start_date"])
                end = datetime.fromisoformat(state.slots["end_date"])
                if exp.bill_date and not (start <= exp.bill_date <= end):
                    return StateMachineResult(
                        handled=True,
                        assistant_message=(
                            f"Expense **#{eid}** is outside the selected date range. "
                            "Choose an ID from the list or provide a new date range."
                        ),
                        updated_state=state,
                    )
            except (TypeError, ValueError):
                pass

        state.fill_slot("expense_id", eid)
        if "expense_id" in state.pending_slots:
            state.pending_slots.remove("expense_id")

        updates = parse_expense_field_updates(text) if action == "update" else parse_slot_updates(text)
        if action == "update" and updates:
            state.slots["pending_updates"] = updates
            return self._ready_update(state, eid, updates)

        return self._complete_pick(state, action, eid)

    def _complete_pick(
        self,
        state: ConversationWorkflowState,
        action: ManageAction,
        expense_id: int,
    ) -> StateMachineResult:
        if action == "delete":
            return StateMachineResult(
                handled=True,
                ready_tool_name="expense.delete.v1",
                ready_arguments={"expense_id": expense_id},
                updated_state=state,
                clear_state=True,
            )

        if state.slots.get("pending_updates"):
            return self._ready_update(
                state, expense_id, state.slots["pending_updates"]
            )

        state.pending_slots.append("changes")
        return StateMachineResult(
            handled=True,
            assistant_message=(
                f"Expense **#{expense_id}** selected. What should I change? "
                "You can say e.g. **amount 500**, **vendor Ghiotto**, **category food**, "
                "or **date 14 Oct 2024**."
            ),
            updated_state=state,
        )

    def _handle_changes(
        self,
        text: str,
        state: ConversationWorkflowState,
    ) -> StateMachineResult:
        expense_id = state.slots.get("expense_id")
        if not expense_id:
            return StateMachineResult(handled=False)

        updates = parse_expense_field_updates(text)
        if not updates and text.strip():
            from app.ai.tools.argument_normalizer import normalize_tool_arguments

            norm = normalize_tool_arguments({"bill_amount": text})
            if isinstance(norm.get("bill_amount"), (int, float)):
                updates["bill_amount"] = norm["bill_amount"]

        if not updates:
            return StateMachineResult(
                handled=True,
                assistant_message=(
                    "Tell me what to update — **amount**, **vendor**, **category**, or **date**."
                ),
                updated_state=state,
            )

        state.slots["pending_updates"] = updates
        if "changes" in state.pending_slots:
            state.pending_slots.remove("changes")
        return self._ready_update(state, int(expense_id), updates)

    def _ready_update(
        self,
        state: ConversationWorkflowState,
        expense_id: int,
        updates: Dict[str, Any],
    ) -> StateMachineResult:
        args: Dict[str, Any] = {"expense_id": expense_id}
        field_map = {
            "bill_amount": "bill_amount",
            "vendor_name": "vendor_name",
            "main_category": "main_category",
            "sub_category": "sub_category",
            "bill_date": "bill_date",
        }
        for src, dst in field_map.items():
            if updates.get(src) is not None:
                args[dst] = updates[src]
        if not args or args.keys() == {"expense_id"}:
            state.pending_slots.append("changes")
            return StateMachineResult(
                handled=True,
                assistant_message="What field should I update on this expense?",
                updated_state=state,
            )
        return StateMachineResult(
            handled=True,
            ready_tool_name="expense.update.v1",
            ready_arguments=args,
            updated_state=state,
            clear_state=True,
        )
