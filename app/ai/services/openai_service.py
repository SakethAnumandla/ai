"""Centralized async OpenAI client with tool calling, retries, and fallback."""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError

from app.ai.schemas.audit import TokenUsage
from app.ai.schemas.openai_result import ChatWithToolsResult, ToolCallPlan
from app.config import settings

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_TURN = 5


class OpenAIService:
    """OpenAI wrapper — never touches the database."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        temperature: Optional[float] = None,
    ):
        key = api_key or settings.openai_api_key
        self._primary_model = primary_model or settings.openai_primary_model or settings.openai_model
        self._fallback_model = fallback_model or settings.openai_fallback_model
        self._timeout = timeout if timeout is not None else settings.openai_timeout_seconds
        self._max_retries = max_retries if max_retries is not None else settings.openai_max_retries
        self._temperature = temperature if temperature is not None else settings.openai_temperature
        self._client: Optional[AsyncOpenAI] = None
        self._api_key = key
        self._last_model_used = self._primary_model

    @property
    def model(self) -> str:
        return self._last_model_used

    def _ensure_client(self) -> AsyncOpenAI:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                timeout=self._timeout,
                max_retries=0,
            )
        return self._client

    def _parse_tool_calls(self, message: Any) -> List[ToolCallPlan]:
        plans: List[ToolCallPlan] = []
        raw_calls = getattr(message, "tool_calls", None) or []
        for tc in raw_calls[:MAX_TOOL_CALLS_PER_TURN]:
            fn = tc.function
            try:
                args = json.loads(fn.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            plans.append(ToolCallPlan(id=tc.id, name=fn.name, arguments=args))
        return plans

    async def _call_model(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
    ) -> ChatWithToolsResult:
        client = self._ensure_client()
        last_error: Optional[Exception] = None
        start = time.perf_counter()

        for attempt in range(1, self._max_retries + 1):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": self._temperature,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice

                response = await client.chat.completions.create(**kwargs)
                latency_ms = int((time.perf_counter() - start) * 1000)
                choice = response.choices[0]
                msg = choice.message
                usage = response.usage
                token_usage = TokenUsage(
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                )
                self._last_model_used = model
                return ChatWithToolsResult(
                    content=msg.content or "",
                    tool_calls=self._parse_tool_calls(msg),
                    token_usage=token_usage,
                    latency_ms=latency_ms,
                    model=model,
                )
            except APITimeoutError as exc:
                last_error = exc
            except RateLimitError as exc:
                last_error = exc
                await asyncio.sleep(min(2 ** attempt, 30))
            except APIError as exc:
                last_error = exc
                if exc.status_code and exc.status_code < 500:
                    raise
                await asyncio.sleep(min(2 ** attempt, 15))

        raise last_error or RuntimeError(f"OpenAI request failed for model {model}")

    async def chat_reply(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: Optional[float] = None,
    ) -> ChatWithToolsResult:
        """Single-turn or multi-turn chat without tools (greetings, welcome, polish)."""
        temp = self._temperature if temperature is None else temperature
        saved = self._temperature
        self._temperature = temp
        try:
            return await self._call_model(self._primary_model, messages)
        except (APITimeoutError, APIError, RuntimeError) as primary_exc:
            if self._fallback_model == self._primary_model:
                raise
            logger.warning("openai.reply.fallback %s -> %s", self._primary_model, self._fallback_model)
            try:
                return await self._call_model(self._fallback_model, messages)
            except Exception:
                raise primary_exc
        finally:
            self._temperature = saved

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: List[Dict[str, Any]],
    ) -> ChatWithToolsResult:
        """Strict schema-bound tool calling; registered tools only."""
        try:
            return await self._call_model(self._primary_model, messages, tools=tools)
        except (APITimeoutError, APIError, RuntimeError) as primary_exc:
            if self._fallback_model == self._primary_model:
                raise
            logger.warning("openai.fallback %s -> %s", self._primary_model, self._fallback_model)
            try:
                return await self._call_model(self._fallback_model, messages, tools=tools)
            except Exception:
                raise primary_exc

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> tuple[str, TokenUsage, int]:
        result = await self.chat_with_tools(
            messages,
            tools=tools or [],
        ) if tools else await self._call_model(self._primary_model, messages)
        return result.content, result.token_usage, result.latency_ms

    async def generate_summary(self, conversation_text: str, system_prompt: str) -> tuple[str, TokenUsage, int]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": conversation_text},
        ]
        result = await self._call_model(self._primary_model, messages)
        return result.content, result.token_usage, result.latency_ms

    async def extract_json(
        self,
        *,
        system_prompt: str,
        user_content: str,
    ) -> Dict[str, Any]:
        """Structured JSON extraction (e.g. expense fields) with primary/fallback models."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        client = self._ensure_client()
        last_error: Optional[Exception] = None
        for model in (self._primary_model, self._fallback_model):
            if model == self._fallback_model and model == self._primary_model:
                continue
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                self._last_model_used = model
                content = response.choices[0].message.content or "{}"
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning("openai.extract_json invalid JSON from %s", model)
                return {}
            except (APITimeoutError, APIError) as exc:
                last_error = exc
                if model == self._primary_model and self._fallback_model != self._primary_model:
                    logger.warning("openai.extract_json fallback %s -> %s", model, self._fallback_model)
                    continue
                raise
        raise last_error or RuntimeError("OpenAI JSON extraction failed")
