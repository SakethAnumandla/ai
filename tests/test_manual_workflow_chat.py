"""Manual expense chat workflow — role skip, attachment summary, post-save follow-up."""
from app.ai.conversation.post_save import is_post_save_accept, is_post_save_decline
from app.ai.conversation.state_machine import (
    ConversationStateMachine,
    _GOT_IT_AFTER_ATTACHMENT,
    _POST_SAVE_FOLLOWUP_QUESTION,
)
from app.ai.schemas.workflow import ConversationWorkflowState, WorkflowScope, WorkflowType
from app.ai.workflow.engine import WorkflowEngine
from app.ai.workflow.manual_slots import try_fill_manual_slot


def test_role_skip_is_not_stored_as_value():
    val, err = try_fill_manual_slot("submitted_by_role", "skip", slots={})
    assert val is None
    assert err is None


def test_role_skip_advances_to_next_slot():
    sm = ConversationStateMachine()
    state = ConversationWorkflowState(
        workflow_type=WorkflowType.EXPENSE_CREATE,
        scope=WorkflowScope.EXPENSE,
        slots={"creation_mode": "manual", "submitted_by_name": "Abhinav B"},
        pending_slots=["submitted_by_role", "bill_date"],
    )
    result = sm.process_turn("skip", state)
    assert result.handled
    assert result.updated_state.slots.get("submitted_by_role") is None
    assert "submitted_by_role" in result.updated_state.slots.get("_skipped_slots", [])
    assert result.updated_state.pending_slots[0] == "bill_date"
    assert "date" in (result.assistant_message or "").lower()


def test_manager_after_role_skip_fills_date_not_role():
    sm = ConversationStateMachine()
    state = ConversationWorkflowState(
        workflow_type=WorkflowType.EXPENSE_CREATE,
        scope=WorkflowScope.EXPENSE,
        slots={
            "creation_mode": "manual",
            "submitted_by_name": "Abhinav B",
            "_skipped_slots": ["submitted_by_role"],
        },
        pending_slots=["bill_date"],
    )
    result = sm.process_turn("today", state)
    assert result.handled
    assert result.updated_state.slots.get("bill_date") is not None
    assert result.updated_state.slots.get("submitted_by_role") is None


def test_attachment_skip_shows_short_got_it_only():
    sm = ConversationStateMachine()
    state = ConversationWorkflowState(
        workflow_type=WorkflowType.EXPENSE_CREATE,
        scope=WorkflowScope.EXPENSE,
        slots={
            "creation_mode": "manual",
            "bill_name": "Uber",
            "bill_amount": 450,
            "vendor_name": "Uber",
            "main_category": "travel_transportation",
            "sub_category": "vehicle_expenses",
            "line_item": "vehicle_maintenance",
            "tax_amount": 0,
            "submitted_by_name": "Abhinav B",
            "submitted_by_role": "manager",
            "bill_date": "2026-06-16",
            "description": "Uber ride",
            "_awaiting_attachment": True,
        },
        pending_slots=[],
        expense_id=99,
    )
    result = sm.process_turn("skip", state)
    assert result.handled
    assert result.assistant_message == _GOT_IT_AFTER_ATTACHMENT
    assert "Expense details" not in (result.assistant_message or "")


def test_post_save_decline_and_accept():
    assert is_post_save_decline("no")
    assert is_post_save_decline("nothing else")
    assert is_post_save_accept("yes")
    assert not is_post_save_decline("yes")


def test_post_save_followup_state_factory():
    state = WorkflowEngine.post_save_followup_state(session_id="sess-123")
    assert state.slots["_awaiting_post_save_followup"] is True
    assert state.session_id == "sess-123"


def test_post_save_followup_question_constant():
    assert "anything else" in _POST_SAVE_FOLLOWUP_QUESTION.lower()


def test_format_bill_date_display_from_iso():
    from app.ai.schemas.chat_ui import format_bill_date_display

    assert format_bill_date_display("2026-06-16T00:00:00+00:00") == "16/06/2026"
    assert format_bill_date_display("2026-06-16") == "16/06/2026"


def test_manual_attach_complete_sets_submit_confirm_and_got_it():
    from unittest.mock import MagicMock, patch

    from app.ai.manual_chat_upload import attach_receipt_to_manual_workflow
    from app.ai.conversation.state_machine import _SUBMIT_CONFIRM_SLOT

    state = ConversationWorkflowState(
        workflow_type=WorkflowType.EXPENSE_CREATE,
        scope=WorkflowScope.EXPENSE,
        slots={
            "creation_mode": "manual",
            "bill_name": "Wifi bill",
            "bill_amount": 500,
            "vendor_name": "Airtel",
            "main_category": "office_facilities",
            "sub_category": "utilities",
            "line_item": "internet_broadband",
            "tax_amount": 0,
            "submitted_by_name": "Abhinav B",
            "submitted_by_role": "manager",
            "bill_date": "2026-06-16",
            "description": "create an expense",
            "_awaiting_attachment": True,
            "expense_id": 42,
        },
        pending_slots=[],
        expense_id=42,
    )
    user = MagicMock(id=1, company_id=1)
    db = MagicMock()
    expense = MagicMock(id=42, user_id=1, company_id=1, files=[MagicMock()])
    db.query.return_value.filter.return_value.first.return_value = expense
    file_infos = [{"file_name": "bill.jpg", "file_data": b"x", "file_size": 1, "mime_type": "image/jpeg"}]

    with patch("app.ai.manual_chat_upload.persist_workflow_draft", return_value=(state, 42)), patch(
        "app.ai.manual_chat_upload.attach_files_to_expense"
    ), patch("app.ai.manual_chat_upload.build_workflow_preview_card") as preview_mock:
        preview_mock.return_value = MagicMock(actions=[MagicMock(action="submit")])
        updated, preview, message, _, actions = attach_receipt_to_manual_workflow(
            db, user, state, file_infos
        )

    assert message == _GOT_IT_AFTER_ATTACHMENT
    assert updated.slots.get("_bill_attached") is True
    assert updated.slots.get(_SUBMIT_CONFIRM_SLOT) is True
    assert preview is not None
    assert actions
