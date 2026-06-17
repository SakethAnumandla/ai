from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.ai.schemas.chat_ui import ChatUIAction, ExpensePreviewCard, CategoryPickerPayload
from app.ai.schemas.classification import ResponseClassificationOut
from app.ai.schemas.conversation import ConversationMessageOut


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str = Field(..., min_length=8, max_length=64)


class ChatActionRequest(BaseModel):
    """Preview-card button actions from the chat client."""

    session_id: str = Field(..., min_length=8, max_length=64)
    action: str = Field(..., description="submit | edit | delete")
    expense_id: int = Field(..., ge=1)
    fields: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional field updates when action=edit",
    )


class ChatResponse(BaseModel):
    message: ConversationMessageOut
    session_id: str
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    classification: Optional[ResponseClassificationOut] = None
    requires_confirmation: bool = False
    confirmation_token: Optional[str] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    attachments_enabled: bool = Field(
        default=False,
        description="When true, client may show inline attachment on the chat input (deprecated — prefer ui_actions).",
    )
    expense_previews: Optional[List[ExpensePreviewCard]] = None
    ui_actions: Optional[List[ChatUIAction]] = None
    category_picker: Optional[CategoryPickerPayload] = None
