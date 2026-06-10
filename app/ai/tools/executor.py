"""Tool executor — timeout enforcement, circuit breaker, idempotency wrapper."""
import asyncio
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from app.ai.idempotency.service import IdempotencyService
from app.ai.observability import get_trace_context
from app.ai.schemas.common import SessionContext
from app.ai.schemas.tool_result import ToolResult
from app.ai.tools.circuit_breaker import ToolCircuitBreaker
from app.config import settings
from app.models import User

logger = logging.getLogger(__name__)

ToolCallable = Callable[..., ToolResult | Awaitable[ToolResult]]

# Tools that require idempotency_key when performing mutating actions
_IDEMPOTENT_TOOLS = frozenset({
    "expense.submit.v1",
    "approval.submit.v1",
    "reimbursement.submit.v1",
    "submit_expense",  # legacy alias
})


class ToolTimeoutError(Exception):
    pass


class ToolCircuitOpenError(Exception):
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        super().__init__(f"Tool temporarily disabled due to repeated failures: {tool_name}")


class ToolExecutor:
    """Runs validated tool handlers with timeout and circuit breaker protection."""

    def __init__(
        self,
        *,
        circuit_breaker: Optional[ToolCircuitBreaker] = None,
        idempotency: Optional[IdempotencyService] = None,
        timeout_seconds: Optional[float] = None,
    ):
        self._circuit = circuit_breaker or ToolCircuitBreaker()
        self._idempotency = idempotency
        self._timeout = timeout_seconds if timeout_seconds is not None else settings.max_tool_execution_seconds

    @property
    def circuit_breaker(self) -> ToolCircuitBreaker:
        return self._circuit

    async def execute(
        self,
        *,
        tool_name: str,
        handler: ToolCallable,
        user: User,
        ctx: SessionContext,
        arguments: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        action_type: Optional[str] = None,
    ) -> ToolResult:
        trace = get_trace_context()
        log_extra = {
            "tool_name": tool_name,
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            **(trace.log_extra() if trace else {}),
        }

        if not self._circuit.allow_execution(tool_name):
            return ToolResult.fail(
                f"Tool '{tool_name}' is temporarily unavailable. Please try again later.",
                error="circuit_open",
            )

        if tool_name in _IDEMPOTENT_TOOLS or (action_type and idempotency_key):
            if not idempotency_key:
                return ToolResult.fail(
                    "idempotency_key is required for this action",
                    error="missing_idempotency_key",
                )
            if self._idempotency is None:
                return ToolResult.fail(
                    "Idempotency service unavailable",
                    error="idempotency_unavailable",
                )
            cached = self._idempotency.get_existing(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                idempotency_key=idempotency_key,
                action_type=action_type or tool_name,
            )
            if cached is not None:
                logger.info("tool.idempotency.hit", extra=log_extra)
                return ToolResult.model_validate(cached)

        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._invoke_handler(handler, user=user, ctx=ctx, arguments=arguments),
                timeout=self._timeout,
            )
            if not isinstance(result, ToolResult):
                result = ToolResult.fail("Tool returned invalid result type", error="invalid_result")
            if result.success:
                self._circuit.record_success(tool_name)
            else:
                self._circuit.record_failure(tool_name)

            if idempotency_key and self._idempotency and result.success:
                self._idempotency.store(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    idempotency_key=idempotency_key,
                    action_type=action_type or tool_name,
                    result=result,
                )

            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "tool.executed",
                extra={**log_extra, "success": result.success, "latency_ms": latency_ms},
            )
            return result

        except asyncio.TimeoutError:
            self._circuit.record_failure(tool_name)
            logger.error(
                "tool.timeout",
                extra={**log_extra, "timeout_seconds": self._timeout},
            )
            return ToolResult.fail(
                f"Tool '{tool_name}' timed out after {self._timeout}s",
                error="tool_timeout",
            )
        except Exception as exc:
            self._circuit.record_failure(tool_name)
            logger.exception("tool.error", extra=log_extra)
            return ToolResult.fail(str(exc)[:500], error="tool_error")

    async def _invoke_handler(
        self,
        handler: ToolCallable,
        *,
        user: User,
        ctx: SessionContext,
        arguments: Dict[str, Any],
    ) -> ToolResult:
        if inspect.iscoroutinefunction(handler):
            return await handler(user=user, ctx=ctx, **arguments)
        return await asyncio.to_thread(handler, user=user, ctx=ctx, **arguments)
