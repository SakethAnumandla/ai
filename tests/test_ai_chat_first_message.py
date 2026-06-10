"""Regression: first user message must not be answered with welcome-only lag."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.orchestrator.base import AIOrchestrator
from app.ai.prompts.welcome import CHAT_WELCOME_MESSAGE
from app.ai.schemas.common import SessionContext


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    user.department = None
    return user


@pytest.fixture
def session_ctx():
    return SessionContext(tenant_id=1, user_id=1, session_id="bizwy-test01")


@pytest.mark.asyncio
async def test_first_hi_gets_conversational_reply_not_welcome(mock_user, session_ctx):
    """When welcome is missing, store it silently but reply to 'hi' immediately."""
    db = MagicMock()
    orchestrator = AIOrchestrator(
        db=db,
        memory_service=AsyncMock(),
        openai_service=AsyncMock(),
        audit_service=MagicMock(),
        session_lock_manager=MagicMock(),
        tool_executor=AsyncMock(),
        confirmation_service=MagicMock(),
        cost_tracking=MagicMock(),
    )

    orchestrator._session_has_welcome = AsyncMock(return_value=False)
    orchestrator._has_active_expense_workflow = AsyncMock(return_value=False)
    orchestrator._ensure_welcome_stored_fast = AsyncMock()
    orchestrator.store_memory = AsyncMock()
    orchestrator._continue_active_workflow = AsyncMock(return_value=None)
    orchestrator._try_list_pending_bills = AsyncMock(return_value=None)

    greeting_response = {
        "message": MagicMock(
            content="Hey! 👋 How are you doing today?",
            metadata={},
        ),
        "session_id": session_ctx.session_id,
    }
    orchestrator._intercept_conversational = AsyncMock(return_value=greeting_response)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lock(*_args, **_kwargs):
        yield

    import app.ai.orchestrator.base as base_mod

    base_mod.session_lock = _noop_lock

    result = await orchestrator.handle_user_message(
        session_ctx, "hi", user=mock_user
    )

    orchestrator._ensure_welcome_stored_fast.assert_awaited_once()
    orchestrator.store_memory.assert_awaited()
    orchestrator._intercept_conversational.assert_awaited_once()
    assert result is greeting_response
    assert CHAT_WELCOME_MESSAGE not in (result["message"].content or "")
