"""Distributed tracing context: request_id, trace_id, session_id."""
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Optional

_trace_ctx: ContextVar[Optional["TraceContext"]] = ContextVar("ai_trace_context", default=None)


@dataclass(frozen=True)
class TraceContext:
    request_id: str
    trace_id: str
    session_id: Optional[str] = None

    def log_extra(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
        }


def new_trace_context(*, session_id: Optional[str] = None) -> TraceContext:
    return TraceContext(
        request_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        session_id=session_id,
    )


def set_trace_context(ctx: TraceContext) -> None:
    _trace_ctx.set(ctx)


def get_trace_context() -> Optional[TraceContext]:
    return _trace_ctx.get()


def get_or_create_trace_context(*, session_id: Optional[str] = None) -> TraceContext:
    existing = get_trace_context()
    if existing:
        if session_id and not existing.session_id:
            return TraceContext(
                request_id=existing.request_id,
                trace_id=existing.trace_id,
                session_id=session_id,
            )
        return existing
    ctx = new_trace_context(session_id=session_id)
    set_trace_context(ctx)
    return ctx
