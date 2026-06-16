"""Multi-turn slot filling for expense workflows without extra GPT calls."""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.ai.schemas.chat_ui import ChatUIAction

from app.ai.conversation.expense_intent import describes_new_expense
from app.ai.vendor_guard import looks_like_chat_command
from app.ai.schemas.memory import DraftExpenseContext
from app.ai.schemas.workflow import (
    ConversationWorkflowState,
    StateMachineResult,
    WorkflowScope,
    WorkflowType,
)
from app.ai.tools.argument_repair import _coerce_float, _coerce_int
from app.ai.tools.expense_create_enrichment import bill_name_needs_repair
from app.ai.expense_extraction import user_description_from_message
from app.ai.workflow.entity_extractor import ExpenseEntityExtractor
# Legacy non-manual chat order (OCR / quick capture)
_LEGACY_SLOT_ORDER = ["bill_amount", "vendor_name", "main_category", "payment_method"]
_SLOT_ORDER = _LEGACY_SLOT_ORDER  # backwards compat alias

_SLOT_QUESTIONS = {
    "bill_amount": "What was the amount?",
    "vendor_name": "Which merchant or vendor was this with?",
    "payment_method": "How was this paid? (e.g. UPI, credit card, cash)",
    "main_category": "Which category should I use? (e.g. travel, food, miscellaneous)",
    "description": "What description should I use for this expense?",
    "sub_category": (
        "What type of food expense is this? "
        "(e.g. restaurant, dining, cafe, office lunch, groceries)"
    ),
}

# OCR / receipt field names → workflow slot names
_OCR_FIELD_TO_SLOT = {
    "merchant": "vendor_name",
    "total": "bill_amount",
    "invoice_date": "bill_date",
    "invoice_id": "bill_number",
}

_SKIP_PENDING_SLOTS = frozenset({"human_review", "bill_date", "bill_number"})


def _sanitize_sub_category(
    main_category: Optional[str],
    sub_category: Optional[str],
    **kwargs,
):
    from app.ai.workflow.slot_parser import sanitize_sub_category

    return sanitize_sub_category(main_category, sub_category, **kwargs)


def _infer_food_sub_category(**kwargs):
    from app.ai.workflow.slot_parser import infer_food_sub_category

    return infer_food_sub_category(**kwargs)


def normalize_workflow_pending_slots(fields: List[str]) -> List[str]:
    """Map receipt OCR field labels to conversation slot keys."""
    out: List[str] = []
    valid = set(_SLOT_QUESTIONS.keys())
    for raw in fields:
        if raw in _SKIP_PENDING_SLOTS:
            continue
        slot = _OCR_FIELD_TO_SLOT.get(raw, raw)
        if slot in valid:
            out.append(slot)
    return list(dict.fromkeys(out))


def _is_manual(slots: Dict[str, Any]) -> bool:
    return slots.get("creation_mode") == "manual"


def _active_slot_order(slots: Dict[str, Any]) -> List[str]:
    if _is_manual(slots):
        from app.ai.workflow.manual_slots import manual_slot_order

        return manual_slot_order()
    return list(_LEGACY_SLOT_ORDER)


def slot_question(slot: str, *, slots: Optional[Dict[str, Any]] = None) -> str:
    if slots and _is_manual(slots):
        from app.ai.workflow.manual_slots import slot_question as manual_q

        return manual_q(slot)
    return _SLOT_QUESTIONS.get(
        slot,
        f"Could you confirm the {slot.replace('_', ' ')}?",
    )


def _prompt_for_slot(
    state: ConversationWorkflowState,
    slot: str,
    *,
    intro: Optional[str] = None,
    sync_draft: bool = False,
) -> StateMachineResult:
    msg = slot_question(slot, slots=state.slots)
    if intro:
        msg = f"{intro} {msg}"
    ui_actions = None
    category_picker = None
    if _is_manual(state.slots) and slot in ("main_category", "sub_category", "line_item"):
        from app.ai.workflow.manual_slots import build_category_picker, category_ui_actions

        category_picker = build_category_picker(slot, slots=state.slots)
        ui_actions = category_ui_actions(slot, slots=state.slots)
    return StateMachineResult(
        handled=True,
        assistant_message=msg,
        updated_state=state,
        ui_actions=ui_actions,
        category_picker=category_picker,
        sync_draft=sync_draft,
    )


def _detect_creation_mode(text: str) -> Optional[str]:
    if _MANUAL_CHOICE_RE.search(text or ""):
        return "manual"
    if _UPLOAD_CHOICE_RE.search(text or ""):
        return "ocr"
    return None


def _detect_multi_bill_labels(text: str) -> List[str]:
    m = _MULTI_BILL_RE.search(text or "")
    if not m:
        return []
    groups = [g for g in m.groups() if g]
    if len(groups) >= 2:
        return [groups[0].lower(), groups[1].lower()]
    return []


def merge_ocr_prefill_into_state(
    state: ConversationWorkflowState,
    prefill: Dict[str, Any],
    *,
    expense_id: Optional[int] = None,
) -> ConversationWorkflowState:
    """Mid-manual upload: OCR overwrites collected slots with scanned values."""
    mapping = {
        "bill_name": prefill.get("bill_name"),
        "bill_amount": prefill.get("bill_amount"),
        "vendor_name": prefill.get("vendor_name") or prefill.get("restaurant_name"),
        "main_category": prefill.get("main_category"),
        "sub_category": prefill.get("sub_category"),
        "payment_method": prefill.get("payment_method"),
        "description": prefill.get("description"),
        "bill_date": prefill.get("bill_date"),
    }
    for key, val in mapping.items():
        if val is not None and val != "":
            state.slots[key] = val
    if expense_id:
        state.expense_id = expense_id
        state.slots["expense_id"] = expense_id
    state.slots["creation_mode"] = "ocr"
    state.slots.pop(_MANUAL_ATTACHMENT_SLOT, None)
    state.slots.pop(_CREATION_MODE_SLOT, None)
    sm = ConversationStateMachine()
    state.pending_slots = sm._recompute_pending_slots(state.slots)
    if not state.pending_slots:
        state.slots[_SUBMIT_CONFIRM_SLOT] = True
    state.updated_at = datetime.utcnow()
    return state

_CREATE_PATTERNS = [
    re.compile(r"\b(add|create|log|record|save)\b.*\b(expense|bill|receipt)\b", re.I),
    re.compile(r"\b(save|add|log|record)\s+it\s+to\s+(?:the\s+)?expense", re.I),
    re.compile(r"\b(travel|lunch|dinner|food|uber|cab|hotel)\s+expense\b", re.I),
    re.compile(r"\bhelp\s+me\s+log\b", re.I),
    re.compile(r"\b(log|record)\s+it\b", re.I),
    re.compile(r"\bhad\s+(lunch|dinner|breakfast|brunch)\b", re.I),
    re.compile(r"\bwent\s+for\b.*\b(?:hotel|restaurant)\b", re.I),
]

_IMMEDIATE_SUBMIT_RE = re.compile(
    r"\b(?:submit|send)\b(?:\s+it)?\s+for\s+approval\b"
    r"|\bsubmit\s+(?:this|the)\s+expense\b"
    r"|\bsubmit\s+for\s+approval\b",
    re.I,
)

_SUBMIT_CONFIRM_SLOT = "_awaiting_submit_confirm"
_CREATION_MODE_SLOT = "_awaiting_creation_mode"
_MANUAL_ATTACHMENT_SLOT = "_awaiting_attachment"
_EDIT_FIELD_SLOT = "_awaiting_edit_field"
_EDIT_TARGET_SLOT = "_edit_target_field"
_MULTI_BILL_QUEUE_SLOT = "_multi_bill_queue"

_EDIT_FIELD_LABELS = {
    "bill_name": "Bill name",
    "vendor_name": "Vendor",
    "bill_amount": "Amount",
    "main_category": "Category",
    "sub_category": "Sub-category",
    "line_item": "Line item",
    "tax_amount": "Tax",
    "submitted_by_name": "Submitted by",
    "submitted_by_role": "Role",
    "bill_date": "Bill date",
    "payment_method": "Payment method",
    "description": "Description",
}

_EDIT_FIELD_ALIASES = {
    "bill name": "bill_name",
    "name": "bill_name",
    "vendor": "vendor_name",
    "merchant": "vendor_name",
    "amount": "bill_amount",
    "category": "main_category",
    "sub category": "sub_category",
    "subcategory": "sub_category",
    "line item": "line_item",
    "tax": "tax_amount",
    "submitted by": "submitted_by_name",
    "role": "submitted_by_role",
    "date": "bill_date",
    "bill date": "bill_date",
    "payment": "payment_method",
    "payment method": "payment_method",
    "description": "description",
    "desc": "description",
}

_CREATION_MODE_QUESTION = (
    "How would you like to create this expense?\n\n"
    "• **Upload** — upload a receipt image or PDF (I'll read it with AI vision)\n"
    "• **Manual** — enter details step by step"
)

_OCR_WAIT_MESSAGE = (
    "Tap **Upload receipt** below to attach your bill (image or PDF). "
    "I'll extract the details automatically.\n\n"
    "You can also say **manual** to enter details yourself, or **cancel** to stop."
)

_MANUAL_ATTACHMENT_QUESTION = (
    "Please attach your bill using **Upload bill** below (JPG, PNG, or PDF). "
    "A receipt is required for manual expenses."
)

_UPLOAD_CHOICE_RE = re.compile(
    r"\b(upload|attach|ocr|scan|pdf|image|receipt|photo|picture)\b", re.I
)
_MANUAL_CHOICE_RE = re.compile(
    r"\b(manual|manually|type|enter|step\s*by\s*step)\b", re.I
)
_MULTI_BILL_RE = re.compile(
    r"\b(\w+)\s+expense\s+and\s+(\w+)\s+expense\b|\b(travel|meal|meals|food|lunch|dinner|hotel|cab|fuel)\b\s+and\s+\b(travel|meal|meals|food|lunch|dinner|hotel|cab|fuel)\b",
    re.I,
)
_EDIT_FIELD_QUESTION = (
    "Which field would you like to change?\n\n"
    "• **Vendor** • **Amount** • **Category** • **Payment** • **Description**\n\n"
    "Tap a field below or type its name."
)

_OCR_CANCEL_RE = re.compile(
    r"\b(cancel|never\s*mind|start\s*over|forget\s+it|stop)\b",
    re.I,
)

_SKIP_ATTACHMENT_RE = re.compile(
    r"^(skip|no|none|later|continue|next)$",
    re.I,
)

_CONTINUE_PATTERNS = [
    re.compile(r"\bcontinue\b.*\b(expense|draft)\b", re.I),
    re.compile(r"\bresume\b.*\b(expense|draft)\b", re.I),
]

_PAYMENT_ALIASES = {
    "upi": "upi",
    "credit": "credit_card",
    "credit card": "credit_card",
    "debit": "debit_card",
    "cash": "cash",
    "wallet": "wallet",
    "net banking": "net_banking",
}


def _extract_expense_label(text: str) -> Optional[str]:
    m = re.search(
        r"\b(?:add|create|log|record)\s+(?:a\s+)?(.+?)\s+expense\b",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(travel|lunch|dinner|food)\s+expense\b", text, re.I)
    if m:
        return m.group(1).strip()
    lowered = text.lower()
    for meal in ("lunch", "dinner", "breakfast", "brunch"):
        if re.search(rf"\bhad\s+{meal}\b", lowered) or f" {meal} " in f" {lowered} ":
            return meal.capitalize()
    return None


def _parse_payment(value: str) -> Optional[str]:
    v = value.strip().lower()
    for alias, canonical in _PAYMENT_ALIASES.items():
        if alias in v:
            return canonical
    return None


def _resolve_edit_field(text: str) -> Optional[str]:
    lowered = (text or "").strip().lower()
    if not lowered:
        return None
    if lowered in _EDIT_FIELD_ALIASES:
        return _EDIT_FIELD_ALIASES[lowered]
    for alias, slot in _EDIT_FIELD_ALIASES.items():
        if alias in lowered:
            return slot
    for slot in _EDIT_FIELD_LABELS:
        if slot.replace("_", " ") in lowered or slot in lowered:
            return slot
    return None


def _summary_ui_actions(state: ConversationWorkflowState) -> List[Any]:
    from app.ai.schemas.chat_ui import workflow_summary_actions

    eid = state.expense_id or state.slots.get("expense_id")
    return workflow_summary_actions(int(eid) if eid else None)


class ConversationStateMachine:
    """Stateful field collection for expense create / continue flows."""

    def should_start_create(self, text: str) -> bool:
        return any(p.search(text) for p in _CREATE_PATTERNS)

    def _recompute_pending_slots(self, slots: Dict[str, Any]) -> List[str]:
        order = _active_slot_order(slots)
        pending = [s for s in order if slots.get(s) in (None, "", [])]
        pending = self._maybe_require_sub_category(slots, pending)
        return [s for s in pending if slots.get(s) in (None, "", [])]

    def _should_prompt_attachment(self, state: ConversationWorkflowState) -> bool:
        s = state.slots
        if not _is_manual(s):
            return False
        if s.get("_attachment_complete") or s.get(_MANUAL_ATTACHMENT_SLOT):
            return False
        if not s.get("main_category"):
            return False
        if not state.pending_slots:
            return False
        return state.pending_slots[0] == "sub_category"

    def _merge_entities_from_message(
        self,
        state: ConversationWorkflowState,
        text: str,
        *,
        entities: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Extract from the full utterance and merge into workflow before any slot question."""
        if entities is None:
            entities = ExpenseEntityExtractor().extract(text)
        extracted = entities.to_slot_prefill()

        from app.ai.workflow.slot_parser import parse_slot_updates

        for k, v in parse_slot_updates(text).items():
            if k.endswith("_raw") or v is None:
                continue
            if k not in extracted or extracted.get(k) in (None, "", []):
                extracted[k] = v

        logger.info("EXTRACTED ENTITIES=%s", extracted)

        manual = _is_manual(state.slots)
        skip_autofill = {
            "bill_name",
            "bill_amount",
            "vendor_name",
            "main_category",
            "sub_category",
            "line_item",
            "description",
            "bill_date",
            "tax_amount",
            "submitted_by_name",
            "submitted_by_role",
        }
        for k, v in extracted.items():
            if v is not None and state.slots.get(k) in (None, "", []):
                if manual and k in skip_autofill:
                    continue
                state.slots[k] = v

        if not manual:
            desc = user_description_from_message(text)
            if desc and not state.slots.get("description"):
                state.slots["description"] = desc
            if entities.bill_name and not state.slots.get("description"):
                state.slots["description"] = entities.bill_name

            label = state.slots.get("bill_name")
            if bill_name_needs_repair(label) and entities.bill_name:
                state.slots["bill_name"] = entities.bill_name
            elif bill_name_needs_repair(label) and state.slots.get("vendor_name"):
                state.slots["bill_name"] = state.slots["vendor_name"]

            self._apply_food_sub_category_inference(state.slots)
        state.pending_slots = self._recompute_pending_slots(state.slots)
        logger.info("WORKFLOW BEFORE QUESTION=%s", state.model_dump())
        logger.info("MISSING FIELDS=%s", state.pending_slots)
        state.updated_at = datetime.utcnow()
        return extracted

    def start_expense_create(
        self,
        text: str,
        *,
        session_id: Optional[str] = None,
        prefill: Optional[Dict[str, Any]] = None,
    ) -> ConversationWorkflowState:
        entities = ExpenseEntityExtractor().extract(text)
        multi_labels = _detect_multi_bill_labels(text)
        slots: Dict[str, Any] = {
            "_source_utterance": text.strip(),
        }
        mode = _detect_creation_mode(text) or (prefill or {}).get("creation_mode")
        if mode != "manual":
            label = _extract_expense_label(text) or entities.bill_name or "expense"
            if multi_labels:
                label = multi_labels[0]
            if bill_name_needs_repair(label) and entities.bill_name:
                label = entities.bill_name
            slots["bill_name"] = label
        if prefill:
            for k, v in prefill.items():
                if v is None:
                    continue
                if k == "sub_category":
                    mapped = _sanitize_sub_category(
                        prefill.get("main_category") or slots.get("main_category"),
                        v,
                        vendor_name=prefill.get("vendor_name") or slots.get("vendor_name"),
                        bill_name=prefill.get("bill_name") or slots.get("bill_name"),
                    )
                    if mapped:
                        slots["sub_category"] = mapped
                    continue
                slots[k] = v

        if multi_labels and len(multi_labels) > 1:
            slots[_MULTI_BILL_QUEUE_SLOT] = multi_labels[1:]

        if mode:
            slots["creation_mode"] = mode

        state = ConversationWorkflowState(
            workflow_type=WorkflowType.EXPENSE_CREATE,
            scope=WorkflowScope.EXPENSE,
            slots=slots,
            pending_slots=_active_slot_order(slots),
            session_id=session_id,
        )
        self._merge_entities_from_message(state, text, entities=entities)
        if not mode and not prefill:
            state.slots[_CREATION_MODE_SLOT] = True
            state.pending_slots = []
        elif mode == "manual":
            state.slots.pop("bill_name", None)
            state.pending_slots = self._recompute_pending_slots(state.slots)
        elif mode == "ocr":
            state.pending_slots = []
        return state

    def start_from_draft(self, draft: DraftExpenseContext, *, session_id: Optional[str] = None) -> ConversationWorkflowState:
        slots: Dict[str, Any] = {
            "bill_name": draft.bill_name or "expense",
            "bill_amount": draft.bill_amount,
            "vendor_name": draft.vendor_name,
            "main_category": draft.main_category,
            "sub_category": draft.sub_category,
        }
        if draft.expense_id:
            slots["expense_id"] = draft.expense_id
        if draft.fields_pending:
            pending = normalize_workflow_pending_slots(draft.fields_pending)
        else:
            pending = [s for s in _active_slot_order(slots) if slots.get(s) in (None, "")]
        pending = [s for s in pending if slots.get(s) in (None, "")]
        if not pending:
            pending = [s for s in _active_slot_order(slots) if slots.get(s) in (None, "")]
        return ConversationWorkflowState(
            workflow_type=WorkflowType.EXPENSE_CONTINUE,
            scope=WorkflowScope.EXPENSE,
            slots=slots,
            pending_slots=pending,
            expense_id=draft.expense_id,
            session_id=session_id,
        )

    def _apply_food_sub_category_inference(self, slots: Dict[str, Any]) -> None:
        """Infer food sub_category once vendor/label are known — never ask in chat."""
        if (slots.get("main_category") or "").lower() != "food":
            return
        if slots.get("sub_category"):
            mapped = _sanitize_sub_category(
                "food",
                slots["sub_category"],
                vendor_name=slots.get("vendor_name"),
                bill_name=slots.get("bill_name"),
            )
            if mapped:
                slots["sub_category"] = mapped
            else:
                slots.pop("sub_category", None)
        inferred = _infer_food_sub_category(
            vendor_name=slots.get("vendor_name"),
            bill_name=slots.get("bill_name"),
        )
        if inferred:
            slots["sub_category"] = inferred

    def _maybe_require_sub_category(
        self, slots: Dict[str, Any], pending: List[str]
    ) -> List[str]:
        if _is_manual(slots):
            return pending
        self._apply_food_sub_category_inference(slots)
        return [s for s in pending if s != "sub_category"]

    def _try_fill_slot(
        self, slot: str, text: str, *, slots: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        stripped = text.strip()
        ctx = slots or {}
        if _is_manual(ctx):
            from app.ai.workflow.manual_slots import (
                resolve_main_categories,
                try_fill_manual_slot,
            )

            if slot == "main_category":
                cats = resolve_main_categories(stripped)
                if cats:
                    ctx["selected_categories"] = cats
                    if len(cats) > 1:
                        ctx["extra_category_tags"] = cats[1:]
                    return cats[0]
            val, _err = try_fill_manual_slot(slot, stripped, slots=ctx)
            if slot == "description" and val is None:
                from app.ai.workflow.manual_slots import _SKIP_RE

                if _SKIP_RE.match(stripped):
                    return ""
            return val

        if slot == "bill_amount":
            val = _coerce_float(stripped)
            return val if val and val > 0 else None
        if slot == "vendor_name":
            if looks_like_chat_command(stripped):
                return None
            if len(stripped) >= 2 and not stripped.isdigit() and len(stripped.split()) <= 5:
                return stripped
            return None
        if slot == "payment_method":
            return _parse_payment(stripped)
        if slot == "main_category":
            if len(stripped) >= 2:
                return stripped.lower().replace(" ", "_")
            return None
        if slot == "sub_category":
            from app.ai.workflow.slot_parser import is_payment_method_text

            if is_payment_method_text(stripped):
                return None
            if len(stripped) >= 2 and not stripped.isdigit():
                return _sanitize_sub_category(
                    ctx.get("main_category"),
                    stripped,
                    vendor_name=ctx.get("vendor_name"),
                    bill_name=ctx.get("bill_name"),
                )
            return None
        return None

    def _wants_immediate_submit(self, text: str) -> bool:
        return bool(_IMMEDIATE_SUBMIT_RE.search(text or ""))

    def _offer_submit_confirmation(
        self, state: ConversationWorkflowState, text: str
    ) -> StateMachineResult:
        """All slots filled — ask to submit unless user already asked to submit now."""
        if _is_manual(state.slots) and not state.slots.get("_attachment_complete"):
            state.slots[_MANUAL_ATTACHMENT_SLOT] = True
            from app.ai.schemas.chat_ui import attachment_prompt_actions

            return StateMachineResult(
                handled=True,
                assistant_message=_MANUAL_ATTACHMENT_QUESTION,
                updated_state=state,
                ui_actions=attachment_prompt_actions(),
                sync_draft=True,
            )
        if self._wants_immediate_submit(text):
            return self._complete(state, submit_now=True)
        state.slots[_SUBMIT_CONFIRM_SLOT] = True
        from app.ai.workflow.draft_summary import format_draft_summary

        return StateMachineResult(
            handled=True,
            assistant_message=format_draft_summary(state.slots, intro="Got it 👍"),
            updated_state=state,
            clear_state=False,
            ui_actions=_summary_ui_actions(state),
            sync_draft=True,
        )

    def _handle_creation_mode_reply(
        self, state: ConversationWorkflowState, text: str
    ) -> Optional[StateMachineResult]:
        if not state.slots.get(_CREATION_MODE_SLOT):
            return None
        mode = _detect_creation_mode(text)
        if not mode:
            return StateMachineResult(
                handled=True,
                assistant_message=_CREATION_MODE_QUESTION,
                updated_state=state,
            )
        state.slots.pop(_CREATION_MODE_SLOT, None)
        state.slots["creation_mode"] = mode
        if mode == "ocr":
            from app.ai.schemas.chat_ui import ocr_upload_actions

            state.pending_slots = []
            return StateMachineResult(
                handled=True,
                assistant_message=_OCR_WAIT_MESSAGE,
                updated_state=state,
                ui_actions=ocr_upload_actions(),
            )
        state.slots.pop("bill_name", None)
        state.pending_slots = self._recompute_pending_slots(state.slots)
        next_slot = state.pending_slots[0] if state.pending_slots else None
        intro = "Sure — let's enter the details manually, same as the manual bill form."
        if state.slots.get(_MULTI_BILL_QUEUE_SLOT):
            queue = state.slots[_MULTI_BILL_QUEUE_SLOT]
            if queue:
                intro += f" We'll do **{queue[0]}** first."
        if next_slot:
            return _prompt_for_slot(state, next_slot, intro=intro)
        return StateMachineResult(
            handled=True,
            assistant_message=intro,
            updated_state=state,
        )

    def _handle_manual_attachment_reply(
        self, state: ConversationWorkflowState, text: str
    ) -> Optional[StateMachineResult]:
        if not state.slots.get(_MANUAL_ATTACHMENT_SLOT):
            return None
        from app.ai.schemas.chat_ui import attachment_prompt_actions

        return StateMachineResult(
            handled=True,
            assistant_message=_MANUAL_ATTACHMENT_QUESTION,
            updated_state=state,
            ui_actions=attachment_prompt_actions(),
            sync_draft=True,
        )

    def _handle_ocr_wait_reply(
        self, state: ConversationWorkflowState, text: str
    ) -> Optional[StateMachineResult]:
        """Let users switch to manual entry or cancel instead of looping on attach prompt."""
        from app.ai.schemas.chat_ui import ocr_upload_actions

        if state.slots.get("creation_mode") != "ocr" or state.slots.get("expense_id"):
            return None

        if _OCR_CANCEL_RE.search(text or ""):
            return StateMachineResult(
                handled=True,
                assistant_message="Okay — cancelled that expense. What would you like to do next?",
                updated_state=None,
                clear_state=True,
            )

        mode = _detect_creation_mode(text)
        if mode == "manual":
            state.slots["creation_mode"] = "manual"
            state.slots.pop(_CREATION_MODE_SLOT, None)
            state.slots.pop("bill_name", None)
            state.pending_slots = self._recompute_pending_slots(state.slots)
            next_slot = state.pending_slots[0] if state.pending_slots else None
            intro = "Sure — let's enter the details manually, same as the manual bill form."
            if next_slot:
                return _prompt_for_slot(state, next_slot, intro=intro)
            return StateMachineResult(
                handled=True,
                assistant_message=intro,
                updated_state=state,
            )

        return StateMachineResult(
            handled=True,
            assistant_message=_OCR_WAIT_MESSAGE,
            updated_state=state,
            ui_actions=ocr_upload_actions(),
        )

    def _handle_pending_submit_reply(
        self, state: ConversationWorkflowState, text: str
    ) -> Optional[StateMachineResult]:
        if not state.slots.get(_SUBMIT_CONFIRM_SLOT):
            return None
        from app.ai.confirmation.affirm import is_denial, is_edit_request, is_submit_confirmation

        if is_edit_request(text):
            state.slots.pop(_SUBMIT_CONFIRM_SLOT, None)
            state.slots[_EDIT_FIELD_SLOT] = True
            from app.ai.schemas.chat_ui import edit_field_actions

            return StateMachineResult(
                handled=True,
                assistant_message=_EDIT_FIELD_QUESTION,
                updated_state=state,
                ui_actions=edit_field_actions(),
            )

        if is_submit_confirmation(text):
            state.slots.pop(_SUBMIT_CONFIRM_SLOT, None)
            return self._complete(state, submit_now=True)
        if is_denial(text):
            state.slots.pop(_SUBMIT_CONFIRM_SLOT, None)
            return StateMachineResult(
                handled=True,
                assistant_message="Okay — I won't submit that expense. Say what you'd like to log next.",
                updated_state=None,
                clear_state=True,
            )
        return None

    def _handle_edit_field_reply(
        self, state: ConversationWorkflowState, text: str
    ) -> Optional[StateMachineResult]:
        if not state.slots.get(_EDIT_FIELD_SLOT):
            return None
        field = _resolve_edit_field(text)
        if not field:
            from app.ai.schemas.chat_ui import edit_field_actions

            return StateMachineResult(
                handled=True,
                assistant_message=_EDIT_FIELD_QUESTION,
                updated_state=state,
                ui_actions=edit_field_actions(),
            )
        state.slots.pop(_EDIT_FIELD_SLOT, None)
        state.slots[_EDIT_TARGET_SLOT] = field
        return _prompt_for_slot(state, field)

    def _handle_edit_value_reply(
        self, state: ConversationWorkflowState, text: str
    ) -> Optional[StateMachineResult]:
        target = state.slots.get(_EDIT_TARGET_SLOT)
        if not target:
            return None
        value = self._try_fill_slot(target, text, slots=state.slots)
        if value is None and target == "description":
            value = text.strip()
        if value is None:
            return StateMachineResult(
                handled=True,
                assistant_message=slot_question(target),
                updated_state=state,
            )
        state.slots[target] = value
        state.slots.pop(_EDIT_TARGET_SLOT, None)
        if _is_manual(state.slots):
            from app.ai.workflow.manual_slots import normalize_slots_taxonomy

            normalize_slots_taxonomy(state.slots)
        else:
            self._apply_food_sub_category_inference(state.slots)
        state.slots[_SUBMIT_CONFIRM_SLOT] = True
        from app.ai.workflow.draft_summary import format_draft_summary

        return StateMachineResult(
            handled=True,
            assistant_message=format_draft_summary(
                state.slots, intro="Updated 👍"
            ),
            updated_state=state,
            ui_actions=_summary_ui_actions(state),
            sync_draft=True,
        )

    def process_turn(
        self,
        text: str,
        state: Optional[ConversationWorkflowState],
        *,
        session_id: Optional[str] = None,
        prefill: Optional[Dict[str, Any]] = None,
    ) -> StateMachineResult:
        if state is None and (self.should_start_create(text) or describes_new_expense(text)):
            state = self.start_expense_create(text, session_id=session_id, prefill=prefill)
            if state.slots.get(_CREATION_MODE_SLOT):
                return StateMachineResult(
                    handled=True,
                    assistant_message=_CREATION_MODE_QUESTION,
                    updated_state=state,
                )
            if state.slots.get("creation_mode") == "ocr" and not state.slots.get("expense_id"):
                from app.ai.schemas.chat_ui import ocr_upload_actions

                ocr_reply = self._handle_ocr_wait_reply(state, text)
                if ocr_reply is not None:
                    return ocr_reply
                return StateMachineResult(
                    handled=True,
                    assistant_message=_OCR_WAIT_MESSAGE,
                    updated_state=state,
                    ui_actions=ocr_upload_actions(),
                )
            if not state.pending_slots:
                return self._offer_submit_confirmation(state, text)
            next_slot = state.pending_slots[0] if state.pending_slots else None
            if next_slot:
                logger.info(
                    "asking slot=%s after first-turn merge pending=%s",
                    next_slot,
                    state.pending_slots,
                )
            return StateMachineResult(
                handled=True,
                assistant_message=slot_question(next_slot, slots=state.slots),
                updated_state=state,
            )

        if state is None:
            return StateMachineResult(handled=False)

        ocr_reply = self._handle_ocr_wait_reply(state, text)
        if ocr_reply is not None:
            return ocr_reply

        mode_reply = self._handle_creation_mode_reply(state, text)
        if mode_reply is not None:
            return mode_reply

        attach_reply = self._handle_manual_attachment_reply(state, text)
        if attach_reply is not None:
            return attach_reply

        edit_field_reply = self._handle_edit_field_reply(state, text)
        if edit_field_reply is not None:
            return edit_field_reply

        edit_value_reply = self._handle_edit_value_reply(state, text)
        if edit_value_reply is not None:
            return edit_value_reply

        pending_submit = self._handle_pending_submit_reply(state, text)
        if pending_submit is not None:
            return pending_submit

        self._merge_entities_from_message(state, text)

        if prefill:
            for k, v in prefill.items():
                if v is None or state.slots.get(k) is not None:
                    continue
                if k == "sub_category":
                    mapped = _sanitize_sub_category(
                        prefill.get("main_category") or state.slots.get("main_category"),
                        v,
                        vendor_name=prefill.get("vendor_name") or state.slots.get("vendor_name"),
                        bill_name=prefill.get("bill_name") or state.slots.get("bill_name"),
                    )
                    if mapped:
                        state.fill_slot(k, mapped)
                    continue
                state.fill_slot(k, v)

        from app.ai.workflow.slot_parser import is_payment_method_text, parse_slot_updates

        explicit_updates = parse_slot_updates(text)

        while state.pending_slots:
            slot = state.pending_slots[0]
            if (
                slot != "payment_method"
                and is_payment_method_text(text)
                and not state.slots.get("payment_method")
            ):
                pay = _parse_payment(text)
                if pay:
                    state.fill_slot("payment_method", pay)
                    self._apply_food_sub_category_inference(state.slots)
                    if not explicit_updates and len(text.split()) <= 6:
                        break
                    continue
            value = self._try_fill_slot(slot, text, slots=state.slots)
            if value is None:
                if slot == state.pending_slots[0] and len(text.split()) <= 6:
                    logger.info(
                        "asking slot=%s short_reply=%r workflow=%s",
                        slot,
                        text[:80],
                        state.slots,
                    )
                    return _prompt_for_slot(state, slot)
                break
            state.fill_slot(slot, value if value != "" else None)
            if slot == "description" and value == "":
                state.slots["description"] = None
            if not _is_manual(state.slots):
                self._apply_food_sub_category_inference(state.slots)
            elif slot in ("main_category", "sub_category", "line_item"):
                from app.ai.workflow.manual_slots import normalize_slots_taxonomy

                normalize_slots_taxonomy(state.slots)
            if self._should_prompt_attachment(state):
                state.slots[_MANUAL_ATTACHMENT_SLOT] = True
                from app.ai.schemas.chat_ui import attachment_prompt_actions

                return StateMachineResult(
                    handled=True,
                    assistant_message=_MANUAL_ATTACHMENT_QUESTION,
                    updated_state=state,
                    ui_actions=attachment_prompt_actions(),
                    sync_draft=True,
                )
            if not explicit_updates and len(text.split()) <= 6:
                break

        if not state.pending_slots:
            return self._offer_submit_confirmation(state, text)

        next_slot = state.pending_slots[0]
        logger.info(
            "asking slot=%s after turn merge pending=%s slots=%s",
            next_slot,
            state.pending_slots,
            state.slots,
        )
        return _prompt_for_slot(state, next_slot)

    def _complete(
        self, state: ConversationWorkflowState, *, submit_now: bool = False
    ) -> StateMachineResult:
        if not state.slots.get("bill_amount"):
            if "bill_amount" not in state.pending_slots:
                state.pending_slots.insert(0, "bill_amount")
            return StateMachineResult(
                handled=True,
                assistant_message=slot_question("bill_amount"),
                updated_state=state,
            )

        self._apply_food_sub_category_inference(state.slots)
        args = dict(state.slots)
        for internal in (
            _SUBMIT_CONFIRM_SLOT,
            _CREATION_MODE_SLOT,
            _MANUAL_ATTACHMENT_SLOT,
            _EDIT_FIELD_SLOT,
            _EDIT_TARGET_SLOT,
            _MULTI_BILL_QUEUE_SLOT,
            "_source_utterance",
            "creation_mode",
            "_attachment_complete",
            "selected_categories",
            "extra_category_tags",
        ):
            args.pop(internal, None)
        bill_name = args.pop("bill_name", "expense")
        payment_method = args.pop("payment_method", None)
        if bill_name_needs_repair(bill_name) and args.get("vendor_name"):
            bill_name = str(args["vendor_name"])
        sub = _sanitize_sub_category(
            args.get("main_category"),
            args.get("sub_category"),
            vendor_name=args.get("vendor_name"),
            bill_name=bill_name,
        )
        tool_args = {
            "bill_name": bill_name,
            "bill_amount": args.get("bill_amount"),
            "vendor_name": args.get("vendor_name"),
            "main_category": args.get("main_category"),
            "save_as_draft": not submit_now,
        }
        if payment_method:
            tool_args["payment_method"] = payment_method
        if sub:
            tool_args["sub_category"] = sub
        if args.get("line_item"):
            tool_args["line_item"] = args.get("line_item")
        if args.get("description"):
            tool_args["description"] = args["description"]
        if args.get("bill_date"):
            tool_args["bill_date"] = args.get("bill_date")
        if args.get("tax_amount") is not None:
            tool_args["tax_amount"] = args.get("tax_amount")
        if args.get("submitted_by_name"):
            tool_args["submitted_by_name"] = args.get("submitted_by_name")
        if args.get("submitted_by_role"):
            tool_args["submitted_by_role"] = args.get("submitted_by_role")
        if state.expense_id:
            tool_args["expense_id"] = state.expense_id

        return StateMachineResult(
            handled=True,
            ready_tool_name="expense.create.v1",
            ready_arguments={k: v for k, v in tool_args.items() if v is not None},
            updated_state=state,
            clear_state=True,
        )

    def state_to_draft(self, state: ConversationWorkflowState) -> DraftExpenseContext:
        return DraftExpenseContext(
            expense_id=state.expense_id,
            bill_name=state.slots.get("bill_name"),
            bill_amount=state.slots.get("bill_amount"),
            vendor_name=state.slots.get("vendor_name"),
            payment_method=state.slots.get("payment_method"),
            main_category=state.slots.get("main_category"),
            sub_category=state.slots.get("sub_category"),
            source_utterance=state.slots.get("_source_utterance")
            or state.slots.get("description"),
            fields_pending=list(state.pending_slots),
        )
