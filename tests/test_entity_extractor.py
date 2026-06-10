"""Expense entity extraction from natural language."""
import pytest

from app.ai.conversation.expense_intent import describes_new_expense
from app.ai.conversation.state_machine import ConversationStateMachine
from app.ai.resolution.reference_resolver import ReferenceResolver
from app.ai.workflow.entity_extractor import ExpenseEntityExtractor


PIZZA_MSG = (
    "i had veg pizza in pizzahut and the bill was 200 and i paid using upi"
)

COFFEE_MSG = (
    "I had coffee at cafe coffee day and the bill was 200 and add it to the expenses"
)

KOI_MSG = (
    "Yesterday I went to Koi and Co, had coffee, the bill was 200 and I paid using UPI"
)


def test_entity_extractor_pizza_hut_message():
    entities = ExpenseEntityExtractor().extract(PIZZA_MSG)
    assert entities.bill_amount == 200
    assert entities.vendor_name == "Pizza Hut"
    assert entities.payment_method == "upi"
    assert entities.main_category == "food"
    assert entities.bill_name == "Veg Pizza"


def test_describes_new_expense_pizza_message():
    assert describes_new_expense(PIZZA_MSG) is True


def test_reference_resolver_prefills_all_slots():
    class _Db:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def order_by(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def all(self):
            return []

    resolved = ReferenceResolver(_Db()).resolve(1, PIZZA_MSG)
    slots = resolved.apply_to_slots({})
    assert slots["bill_amount"] == 200
    assert slots["vendor_name"] == "Pizza Hut"
    assert slots["payment_method"] == "upi"
    assert slots["main_category"] == "food"


def test_entity_extractor_koi_went_to_message():
    entities = ExpenseEntityExtractor().extract(KOI_MSG)
    assert entities.bill_amount == 200
    assert entities.vendor_name == "Koi And Co"
    assert entities.payment_method == "upi"


def test_entity_extractor_coffee_cafe_message():
    entities = ExpenseEntityExtractor().extract(COFFEE_MSG)
    assert entities.bill_amount == 200
    assert entities.vendor_name == "Cafe Coffee Day"
    assert entities.main_category == "food"
    assert entities.bill_name == "Coffee"


def test_state_machine_coffee_message_slots():
    sm = ConversationStateMachine()
    result = sm.process_turn(COFFEE_MSG, None)
    assert result.handled is True
    assert result.updated_state is not None
    slots = result.updated_state.slots
    assert slots["vendor_name"] == "Cafe Coffee Day"
    assert slots["bill_name"] == "Coffee"
    assert slots["bill_amount"] == 200
    assert slots["main_category"] == "food"


MEHFIL_MSG = (
    "i went for a hotel and the hotel name is mehfil and i had chicken biryani "
    "and the bill was 500 and i payed it using upi now save it to expense"
)


def test_entity_extractor_mehfil_hotel_name():
    entities = ExpenseEntityExtractor().extract(MEHFIL_MSG)
    assert entities.bill_amount == 500
    assert entities.vendor_name == "Mehfil"
    assert entities.payment_method == "upi"
    assert entities.main_category == "food"
    assert entities.bill_name == "Chicken Biryani"


def test_state_machine_mehfil_no_vendor_question():
    sm = ConversationStateMachine()
    result = sm.process_turn(MEHFIL_MSG, None)
    assert result.handled is True
    assert result.updated_state is not None
    assert "vendor_name" not in (result.updated_state.pending_slots or [])
    assert "Which merchant" not in (result.assistant_message or "")
    assert result.ready_tool_name is None
    assert "submit" in (result.assistant_message or "").lower()
    assert result.updated_state.slots.get("_awaiting_submit_confirm") is True

    confirmed = sm.process_turn("yes save the bill", result.updated_state)
    assert confirmed.ready_tool_name == "expense.create.v1"
    args = confirmed.ready_arguments
    assert args.get("vendor_name") == "Mehfil"
    assert args.get("bill_amount") == 500
    assert args.get("payment_method") == "upi"
    assert args.get("save_as_draft") is False


def test_state_machine_no_questions_when_fully_extracted():
    sm = ConversationStateMachine()
    result = sm.process_turn(PIZZA_MSG, None)
    assert result.handled is True
    assert result.ready_tool_name is None
    assert result.updated_state is not None
    assert result.updated_state.pending_slots == []
    assert "Pizza Hut" in (result.assistant_message or "")
    assert "₹200" in (result.assistant_message or "")
    assert "upi" in (result.assistant_message or "").lower()
    assert "Which merchant" not in (result.assistant_message or "")
