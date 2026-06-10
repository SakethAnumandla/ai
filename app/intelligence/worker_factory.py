"""Build AI orchestrator inside Celery workers (outside FastAPI request scope)."""
import asyncio

from sqlalchemy.orm import Session

from app.ai.confirmation.service import ConfirmationService
from app.ai.dead_letter.service import DeadLetterQueueService
from app.ai.memory.repository import AIRepository
from app.ai.memory.redis_store import RedisMemoryStore
from app.ai.memory.resilient_store import ResilientMemoryStore
from app.ai.orchestrator.base import AIOrchestrator
from app.ai.services.audit_service import AuditService
from app.ai.services.cost_tracking_service import CostTrackingService
from app.ai.services.memory_service import MemoryService
from app.ai.services.openai_service import OpenAIService
from app.ai.session_lock import SessionLockManager
from app.ai.tools.circuit_breaker import ToolCircuitBreaker
from app.ai.tools.executor import ToolExecutor
from app.ai.idempotency.service import IdempotencyService


def build_orchestrator(db: Session) -> AIOrchestrator:
    redis = RedisMemoryStore()
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(redis.connect())
    except Exception:
        pass

    repo = AIRepository(db)
    store = ResilientMemoryStore(redis, repo)
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(store.connect())
    except Exception:
        pass

    openai = OpenAIService()
    audit = AuditService(repo)
    memory = MemoryService(repo, store, openai, audit)
    locks = SessionLockManager(redis_client=redis._client if redis.is_connected else None)
    executor = ToolExecutor(
        circuit_breaker=ToolCircuitBreaker(),
        idempotency=IdempotencyService(db),
    )

    return AIOrchestrator(
        db,
        memory,
        openai,
        audit,
        locks,
        executor,
        ConfirmationService(db),
        CostTrackingService(db),
        DeadLetterQueueService(db),
    )
