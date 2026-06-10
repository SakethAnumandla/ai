"""Tool execution guardrails — permission matrix + depth + idempotency."""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException, status
from pydantic import BaseModel

from app.ai.confirmation.service import requires_human_confirmation
from app.ai.permissions.matrix import PermissionAction, PermissionScope, ToolPermissionMatrix
from app.ai.schemas.common import SessionContext
from app.ai.tools.registry import ToolRegistry
from app.models import User

logger = logging.getLogger(__name__)


class ToolExecutionDenied(Exception):
    def __init__(self, reason: str, *, code: str = "tool_denied"):
        self.reason = reason
        self.code = code
        super().__init__(reason)


@dataclass
class ToolExecutionPolicy:
    registry: ToolRegistry
    permission_matrix: Optional[ToolPermissionMatrix] = None
    max_execution_depth: int = 3
    _depth: int = field(default=0, init=False)
    _executed_tools: Set[str] = field(default_factory=set, init=False)

    @property
    def matrix(self) -> ToolPermissionMatrix:
        return self.permission_matrix or ToolPermissionMatrix()

    def begin_chain(self) -> "ToolExecutionPolicy":
        return ToolExecutionPolicy(
            registry=self.registry,
            permission_matrix=self.permission_matrix,
            max_execution_depth=self.max_execution_depth,
        )

    def _child(self) -> "ToolExecutionPolicy":
        child = ToolExecutionPolicy(
            registry=self.registry,
            permission_matrix=self.permission_matrix,
            max_execution_depth=self.max_execution_depth,
        )
        child._depth = self._depth + 1
        child._executed_tools = set(self._executed_tools)
        return child

    def validate(
        self,
        *,
        user: User,
        ctx: SessionContext,
        tool_name: str,
        arguments: Dict[str, Any],
        parameter_model: Optional[type[BaseModel]] = None,
        resource_tenant_id: Optional[int] = None,
        resource_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        canonical = self.registry.resolve_name(tool_name)

        if self._depth >= self.max_execution_depth:
            raise ToolExecutionDenied(
                f"Max tool execution depth ({self.max_execution_depth}) exceeded",
                code="max_depth",
            )

        if canonical in self._executed_tools:
            raise ToolExecutionDenied(
                f"Duplicate tool in chain not allowed: {canonical}",
                code="duplicate_tool",
            )

        if resource_tenant_id is not None and resource_tenant_id != ctx.tenant_id:
            raise ToolExecutionDenied("Resource tenant mismatch", code="tenant_mismatch")

        if resource_user_id is not None and resource_user_id != ctx.user_id:
            from app.models import UserRole
            if user.role not in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN):
                raise ToolExecutionDenied("Resource user mismatch", code="user_mismatch")

        scope = self.matrix.scope_for_tool(canonical)
        if not self.matrix.is_allowed(
            user=user,
            tool_name=canonical,
            tenant_id=ctx.tenant_id,
            action=PermissionAction.EXECUTE,
            scope=scope,
        ):
            raise ToolExecutionDenied(
                f"Role {user.role.value} cannot execute {canonical}",
                code="role_denied",
            )

        tool_def = self.registry.get(tool_name)
        if tool_def is None:
            raise ToolExecutionDenied(f"Unknown tool: {tool_name}", code="unknown_tool")

        if tool_def.requires_idempotency and not arguments.get("idempotency_key"):
            raise ToolExecutionDenied(
                "idempotency_key is required for this tool",
                code="missing_idempotency_key",
            )

        if parameter_model is not None:
            clean_args = parameter_model.model_validate(arguments).model_dump()
        else:
            if not isinstance(arguments, dict):
                raise ToolExecutionDenied("Arguments must be a JSON object", code="invalid_args")
            clean_args = dict(arguments)

        self._executed_tools.add(canonical)
        logger.info(
            "tool.policy.allowed",
            extra={
                "tool_name": canonical,
                "user_id": user.id,
                "tenant_id": ctx.tenant_id,
                "depth": self._depth,
            },
        )
        return clean_args

    def needs_confirmation(self, tool_name: str) -> bool:
        tool_def = self.registry.get(tool_name)
        if tool_def is None:
            return requires_human_confirmation(tool_name)
        return requires_human_confirmation(tool_def.name, tool_flag=tool_def.requires_confirmation)

    def next_invocation(self) -> "ToolExecutionPolicy":
        return self._child()


def policy_denied_to_http(exc: ToolExecutionDenied) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": exc.code, "message": exc.reason},
    )
