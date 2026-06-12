"""Run receipt OCR + draft save when users attach bills in AI chat."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.chat_ui import build_expense_preview_cards, format_preview_message
from app.ai.schemas.chat_ui import ExpensePreviewCard
from app.ai.schemas.memory import DraftExpenseContext
from app.intelligence.receipt.pipeline import ReceiptIntelligencePipeline
from app.intelligence.schemas import ReceiptPipelineResult
from app.models import User

logger = logging.getLogger(__name__)

RECEIPT_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "pdf", "webp"})


def is_receipt_file(file_info: dict) -> bool:
    ext = (file_info.get("file_extension") or "").lower()
    if not ext and file_info.get("file_name"):
        parts = file_info["file_name"].rsplit(".", 1)
        ext = parts[-1].lower() if len(parts) > 1 else ""
    return ext in RECEIPT_EXTENSIONS


@dataclass
class ChatReceiptScanOutcome:
    """OCR results and messages for POST /ai/chat/upload."""

    results: List[ReceiptPipelineResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    draft_contexts: List[DraftExpenseContext] = field(default_factory=list)
    expense_previews: List[ExpensePreviewCard] = field(default_factory=list)
    intent_message: str = ""
    persist_message: str = ""
    llm_user_content: str = ""
    assistant_hint: str = ""


def _format_one_result(index: int, result: ReceiptPipelineResult) -> List[str]:
    af = result.autofill
    lines = [f"### Receipt {index}"]
    if result.expense_id:
        lines.append(f"- Draft expense ID: {result.expense_id}")
    if result.ocr_bill_id:
        lines.append(f"- OCR bill record ID: {result.ocr_bill_id}")
    name = af.vendor_name or af.bill_name
    if name:
        lines.append(f"- Merchant / bill name: {name}")
    if af.bill_amount is not None:
        lines.append(f"- Amount: ₹{af.bill_amount:,.2f}")
    if af.main_category:
        lines.append(f"- Category: {af.main_category}")
    if af.payment_method:
        lines.append(f"- Payment: {af.payment_method}")
    lines.append(f"- OCR confidence: {result.overall_confidence:.0%}")
    if result.is_duplicate:
        lines.append("- Duplicate warning: similar bill may already exist for this user")
    if result.requires_human_review:
        lines.append(
            f"- Human review required (status: {result.review_status}, "
            f"token present: {bool(result.review_token)})"
        )
    failed_fraud = [c for c in result.fraud_checks if not c.passed and c.severity in ("error", "critical")]
    if failed_fraud:
        lines.append("- Fraud / policy flags: " + "; ".join(c.message for c in failed_fraud[:3]))
    if af.fields_needing_clarification:
        lines.append(
            "- Fields needing clarification: " + ", ".join(af.fields_needing_clarification)
        )
    if result.assistant_message:
        lines.append(f"- Note: {result.assistant_message}")
    return lines


def build_chat_messages(
    results: List[ReceiptPipelineResult],
    errors: List[str],
    user_message: str,
) -> tuple[str, str, str]:
    """Return (intent_message, persist_message, llm_user_content)."""
    cleaned = (user_message or "").strip()
    blocks: List[str] = []

    if cleaned:
        blocks.append(f"User message: {cleaned}")

    blocks.append(
        "The user attached receipt image(s) or PDF(s) in chat. "
        "OCR has been run and each bill was saved as a DRAFT expense in the database. "
        "Summarize what was extracted, mention expense IDs, and guide next steps "
        "(confirm details, submit for approval, or fix unclear fields). Do not claim "
        "the expense was submitted unless the user confirms."
    )

    if results:
        blocks.append("\n## OCR scan results")
        for i, r in enumerate(results, start=1):
            blocks.extend(_format_one_result(i, r))

    if errors:
        blocks.append("\n## Scan errors")
        blocks.extend(f"- {e}" for e in errors)

    body = "\n".join(blocks)
    attach_names = " ".join(
        f"[Receipt scanned: expense #{r.expense_id}]" for r in results if r.expense_id
    )
    persist = f"{cleaned}\n{attach_names}".strip() if cleaned else attach_names.strip()
    if not persist:
        persist = "[Receipt attachment — OCR draft saved]"

    intent = cleaned or (
        "I attached a receipt. Please review the OCR results and help me with this expense."
    )
    return intent, persist, body


def run_chat_receipt_scans(
    db: Session,
    user: User,
    file_infos: List[dict],
    *,
    user_message: str = "",
    force_rescan: bool = False,
) -> ChatReceiptScanOutcome:
    pipeline = ReceiptIntelligencePipeline(db)
    outcome = ChatReceiptScanOutcome()

    for idx, file_info in enumerate(file_infos):
        name = file_info.get("file_name") or f"file-{idx + 1}"
        try:
            result = pipeline.run_sync(
                user,
                file_info,
                bill_index=idx,
                force_rescan=force_rescan,
            )
            outcome.results.append(result)
            outcome.draft_contexts.append(pipeline.build_draft_context(result))
        except Exception as exc:
            logger.exception("chat.receipt_scan_failed file=%s", name)
            outcome.errors.append(f"{name}: {exc}")

    intent, persist, llm = build_chat_messages(
        outcome.results, outcome.errors, user_message
    )
    outcome.expense_previews = build_expense_preview_cards(db, outcome.results)
    outcome.assistant_hint = format_preview_message(outcome.expense_previews)
    outcome.intent_message = intent
    outcome.persist_message = persist
    outcome.llm_user_content = llm
    return outcome
