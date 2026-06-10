"""Per-tool circuit breaker — disables tools after repeated failures."""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

from app.config import settings

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _CircuitRecord:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    opened_at: float = 0.0
    last_failure_at: float = 0.0


class ToolCircuitBreaker:
    """
    Opens circuit after `failure_threshold` consecutive failures.
    After `recovery_seconds`, allows one half-open probe.
    """

    def __init__(
        self,
        *,
        failure_threshold: int | None = None,
        recovery_seconds: int | None = None,
    ):
        self._failure_threshold = failure_threshold or settings.tool_circuit_failure_threshold
        self._recovery_seconds = recovery_seconds or settings.tool_circuit_recovery_seconds
        self._circuits: Dict[str, _CircuitRecord] = {}

    def _record(self, tool_name: str) -> _CircuitRecord:
        if tool_name not in self._circuits:
            self._circuits[tool_name] = _CircuitRecord()
        return self._circuits[tool_name]

    def _maybe_transition_to_half_open(self, tool_name: str, rec: _CircuitRecord) -> None:
        if rec.state != CircuitState.OPEN:
            return
        if time.monotonic() - rec.opened_at >= self._recovery_seconds:
            rec.state = CircuitState.HALF_OPEN
            logger.info("circuit.half_open tool=%s", tool_name)

    def is_open(self, tool_name: str) -> bool:
        rec = self._record(tool_name)
        self._maybe_transition_to_half_open(tool_name, rec)
        if rec.state == CircuitState.OPEN:
            logger.warning("circuit.open tool=%s failures=%s", tool_name, rec.failure_count)
            return True
        return False

    def allow_execution(self, tool_name: str) -> bool:
        return not self.is_open(tool_name)

    def record_success(self, tool_name: str) -> None:
        rec = self._record(tool_name)
        rec.state = CircuitState.CLOSED
        rec.failure_count = 0
        logger.debug("circuit.success tool=%s", tool_name)

    def record_failure(self, tool_name: str) -> None:
        rec = self._record(tool_name)
        rec.failure_count += 1
        rec.last_failure_at = time.monotonic()
        if rec.state == CircuitState.HALF_OPEN:
            rec.state = CircuitState.OPEN
            rec.opened_at = time.monotonic()
            logger.warning("circuit.reopened tool=%s", tool_name)
            return
        if rec.failure_count >= self._failure_threshold:
            rec.state = CircuitState.OPEN
            rec.opened_at = time.monotonic()
            logger.warning(
                "circuit.opened tool=%s failures=%s threshold=%s",
                tool_name,
                rec.failure_count,
                self._failure_threshold,
            )

    def get_state(self, tool_name: str) -> CircuitState:
        rec = self._record(tool_name)
        self._maybe_transition_to_half_open(tool_name, rec)
        return rec.state
