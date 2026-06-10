"""Summary generation facade."""
from app.ai.schemas.common import SessionContext
from app.ai.services.memory_service import MemoryService


class SummaryGenerator:
    def __init__(self, memory_service: MemoryService):
        self._memory = memory_service

    async def generate_for_session(self, ctx: SessionContext) -> str:
        return await self._memory.generate_summary(ctx)
