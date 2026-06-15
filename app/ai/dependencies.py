"""FastAPI dependency injection for AI services."""
from functools import lru_cache
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.ai.confirmation.service import ConfirmationService
from app.ai.dead_letter.service import DeadLetterQueueService
from app.ai.memory.context_builder import ContextBuilder
from app.ai.copilot.preflight import CopilotPreflight
from app.ai.idempotency.service import IdempotencyService
from app.ai.memory.resilient_store import ResilientMemoryStore
from app.ai.memory.repository import AIRepository
from app.ai.memory.token_budget import TokenBudgetManager
from app.ai.orchestrator.base import AIOrchestrator
from app.ai.permissions.matrix import ToolPermissionMatrix
from app.ai.prompts.versions import PromptResolver
from app.ai.services.audit_service import AuditService
from app.ai.services.cost_tracking_service import CostTrackingService
from app.ai.services.memory_service import MemoryService
from app.ai.services.openai_service import OpenAIService
from app.ai.session_lock import SessionLockManager
from app.ai.tools.circuit_breaker import ToolCircuitBreaker
from app.ai.tools.executor import ToolExecutor
from app.ai.tools.rate_limiter import ToolRateLimiter
from app.database import get_db

_session_lock_manager: Optional[SessionLockManager] = None
_rate_limiter: Optional[ToolRateLimiter] = None


@lru_cache
def get_openai_service() -> OpenAIService:
    return OpenAIService()


@lru_cache
def get_token_budget_manager() -> TokenBudgetManager:
    return TokenBudgetManager()


@lru_cache
def get_tool_circuit_breaker() -> ToolCircuitBreaker:
    return ToolCircuitBreaker()


@lru_cache
def get_tool_rate_limiter() -> ToolRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = ToolRateLimiter()
    return _rate_limiter


def get_session_lock_manager() -> SessionLockManager:
    global _session_lock_manager
    if _session_lock_manager is None:
        _session_lock_manager = SessionLockManager()
    return _session_lock_manager


def get_ai_repository(db: Session = Depends(get_db)) -> AIRepository:
    return AIRepository(db)


def get_ai_audit_service(repo: AIRepository = Depends(get_ai_repository)) -> AuditService:
    return AuditService(repo)


def get_idempotency_service(db: Session = Depends(get_db)) -> IdempotencyService:
    return IdempotencyService(db)


def get_confirmation_service(db: Session = Depends(get_db)) -> ConfirmationService:
    return ConfirmationService(db)


def get_cost_tracking_service(db: Session = Depends(get_db)) -> CostTrackingService:
    return CostTrackingService(db)


def get_dead_letter_service(db: Session = Depends(get_db)) -> DeadLetterQueueService:
    return DeadLetterQueueService(db)


@lru_cache
def get_context_builder() -> ContextBuilder:
    return ContextBuilder()


async def get_ai_memory_service(
    repo: AIRepository = Depends(get_ai_repository),
    openai: OpenAIService = Depends(get_openai_service),
    audit: AuditService = Depends(get_ai_audit_service),
    token_budget: TokenBudgetManager = Depends(get_token_budget_manager),
) -> MemoryService:
    store = ResilientMemoryStore(repo)
    await store.connect()
    return MemoryService(repo, store, openai, audit, token_budget)


def get_copilot_preflight(
    db: Session = Depends(get_db),
    memory: MemoryService = Depends(get_ai_memory_service),
    confirmation: ConfirmationService = Depends(get_confirmation_service),
    repo: AIRepository = Depends(get_ai_repository),
) -> CopilotPreflight:
    return CopilotPreflight(db, memory, repo, confirmation)


def get_permission_matrix(db: Session = Depends(get_db)) -> ToolPermissionMatrix:
    return ToolPermissionMatrix(db)


def get_prompt_resolver(db: Session = Depends(get_db)) -> PromptResolver:
    return PromptResolver(db)


def get_tool_executor(
    idempotency: IdempotencyService = Depends(get_idempotency_service),
    circuit: ToolCircuitBreaker = Depends(get_tool_circuit_breaker),
) -> ToolExecutor:
    return ToolExecutor(circuit_breaker=circuit, idempotency=idempotency)


def get_ai_orchestrator(
    db: Session = Depends(get_db),
    memory: MemoryService = Depends(get_ai_memory_service),
    openai: OpenAIService = Depends(get_openai_service),
    audit: AuditService = Depends(get_ai_audit_service),
    locks: SessionLockManager = Depends(get_session_lock_manager),
    executor: ToolExecutor = Depends(get_tool_executor),
    confirmation: ConfirmationService = Depends(get_confirmation_service),
    cost_tracking: CostTrackingService = Depends(get_cost_tracking_service),
    dead_letter: DeadLetterQueueService = Depends(get_dead_letter_service),
    permission_matrix: ToolPermissionMatrix = Depends(get_permission_matrix),
    rate_limiter: ToolRateLimiter = Depends(get_tool_rate_limiter),
    context_builder: ContextBuilder = Depends(get_context_builder),
    copilot_preflight: CopilotPreflight = Depends(get_copilot_preflight),
) -> AIOrchestrator:
    return AIOrchestrator(
        db,
        memory,
        openai,
        audit,
        locks,
        executor,
        confirmation,
        cost_tracking,
        dead_letter,
        permission_matrix=permission_matrix,
        rate_limiter=rate_limiter,
        context_builder=context_builder,
        copilot_preflight=copilot_preflight,
    )


async def shutdown_ai_services() -> None:
    global _session_lock_manager, _rate_limiter
    _session_lock_manager = None
    _rate_limiter = None
    get_openai_service.cache_clear()
    get_token_budget_manager.cache_clear()
    get_tool_circuit_breaker.cache_clear()
