from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.ai.schemas.classification import ResponseClassificationOut
from app.ai.schemas.conversation import ConversationMessageOut


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str = Field(..., min_length=8, max_length=64)


class ChatResponse(BaseModel):
    message: ConversationMessageOut
    session_id: str
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    classification: Optional[ResponseClassificationOut] = None
    requires_confirmation: bool = False
    confirmation_token: Optional[str] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
