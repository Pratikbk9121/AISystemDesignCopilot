"""
LLM Client using the OpenAI SDK against Tekion's Bifrost gateway.

Provides three interfaces:
    - generate(): plain text generation (also used for multi-query retrieval)
    - generate_structured(): JSON output (architecture / evaluation)
    - generate_streaming(): async chunk iterator

Per-instance token-usage tracking is built in. Each call to the underlying
API updates ``self.usage_totals`` and ``self.estimated_cost_usd``; cache hits
on :class:`CachedLLMClient` correctly do not increment counters because no
API call happens. Surface the totals via :meth:`get_token_usage`.

A fresh ``LLMClient`` is constructed per request (orchestrator builds a new
``SystemDesignGraph`` → new client per query), so the counters naturally
scope to a single user request.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple
import json
import logging

import openai
from openai import AsyncOpenAI
import httpx

from app.core.config import settings
from app.core.llm.parser import parse_json
from app.models.schemas import TokenUsage

logger = logging.getLogger(__name__)

# Module-level flag so we only warn once per process when the gateway
# rejects response_format={"type": "json_object"}.
_JSON_MODE_UNSUPPORTED_WARNED = False

# Per-process set of models we've already warned about missing pricing for.
_PRICING_WARNED: set[str] = set()


# Approximate USD pricing per 1K tokens (prompt, completion).
# Missing entries → cost = 0.0 with a one-time warn. Keep this small —
# only models we actually plug in via Bifrost.
MODEL_PRICING_USD_PER_1K: Dict[str, Tuple[float, float]] = {
    "gpt-4.1-mini": (0.00040, 0.00160),
    "gpt-4.1": (0.00200, 0.00800),
    "gpt-4o-mini": (0.00015, 0.00060),
    "gpt-4o": (0.00250, 0.01000),
}


class LLMClient:
    """
    Async LLM client backed by Tekion's Bifrost gateway.

    Authenticates via the ``x-bf-vk`` header (the SDK still requires an
    ``api_key`` argument, so we pass the same value there — Bifrost
    ignores it).
    """

    def __init__(self, model: str | None = None):
        """
        Args:
            model: Override the configured default model.
        """
        if not settings.tekion_llm_key:
            raise ValueError(
                "Tekion LLM key not configured. Please set TEKION_LLM_KEY in your .env file.\n"
                "Contact #ai-platform-support slack channel to get your key."
            )

        self.model = model or settings.model

        # Inject Bifrost auth + content headers on every request.
        http_client = httpx.AsyncClient(
            headers={
                "x-bf-vk": settings.tekion_llm_key,
                "Content-Type": "application/json",
            },
            timeout=settings.llm_timeout,
        )

        self.client = AsyncOpenAI(
            base_url=settings.bifrost_base_url,
            api_key=settings.tekion_llm_key,  # SDK requires it; gateway ignores it
            http_client=http_client,
            max_retries=settings.max_retries,
        )

        # Per-instance usage accumulator. Updated by ``_record_usage``.
        self.usage_totals: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.estimated_cost_usd: float = 0.0

    def _build_messages(
        self, prompt: str, system_message: str | None = None
    ) -> List[Dict[str, str]]:
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _record_usage(self, usage: Any) -> None:
        """
        Update the per-instance counters from a response.usage object.

        Accepts either the pydantic ``CompletionUsage`` returned by the
        OpenAI SDK or a plain dict (some streaming chunks use a dict).
        Silently no-ops if usage is missing or malformed.
        """
        if usage is None:
            return
        try:
            if hasattr(usage, "prompt_tokens"):
                prompt = int(usage.prompt_tokens or 0)
                completion = int(usage.completion_tokens or 0)
                total = int(usage.total_tokens or 0)
            elif isinstance(usage, dict):
                prompt = int(usage.get("prompt_tokens", 0) or 0)
                completion = int(usage.get("completion_tokens", 0) or 0)
                total = int(usage.get("total_tokens", 0) or 0)
            else:
                return
        except (TypeError, ValueError):
            return

        if total == 0:
            total = prompt + completion

        self.usage_totals["prompt_tokens"] += prompt
        self.usage_totals["completion_tokens"] += completion
        self.usage_totals["total_tokens"] += total

        pricing = MODEL_PRICING_USD_PER_1K.get(self.model)
        if pricing is None:
            if self.model not in _PRICING_WARNED:
                logger.warning(
                    "No pricing entry for model %r; estimated_cost_usd "
                    "will not include this call. Add it to "
                    "MODEL_PRICING_USD_PER_1K in app/core/llm/client.py.",
                    self.model,
                )
                _PRICING_WARNED.add(self.model)
            return
        prompt_rate, completion_rate = pricing
        self.estimated_cost_usd += (prompt / 1000.0) * prompt_rate
        self.estimated_cost_usd += (completion / 1000.0) * completion_rate

    def get_token_usage(self) -> TokenUsage:
        """Snapshot the per-instance usage as a :class:`TokenUsage` model."""
        return TokenUsage(
            prompt_tokens=self.usage_totals["prompt_tokens"],
            completion_tokens=self.usage_totals["completion_tokens"],
            total_tokens=self.usage_totals["total_tokens"],
            estimated_cost_usd=round(self.estimated_cost_usd, 6),
        )

    async def generate(
        self,
        prompt: str,
        system_message: str | None = None,
        json_mode: bool = False,
        **kwargs,
    ) -> str:
        """
        Generate text completion.

        If ``json_mode=True`` we first try the OpenAI ``response_format``
        knob; if the gateway rejects it we fall back to a plain call (the
        caller's prompt must still ask for JSON in that case).
        """
        global _JSON_MODE_UNSUPPORTED_WARNED

        messages = self._build_messages(prompt, system_message)
        request_args: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", settings.temperature),
            "max_tokens": kwargs.get("max_tokens", settings.max_tokens),
        }

        if json_mode:
            try:
                response = await self.client.chat.completions.create(
                    **request_args,
                    response_format={"type": "json_object"},
                )
                self._record_usage(getattr(response, "usage", None))
                return response.choices[0].message.content
            except (openai.BadRequestError, ValueError) as e:
                if not _JSON_MODE_UNSUPPORTED_WARNED:
                    logger.warning(
                        "Bifrost/model rejected response_format=json_object (%s). "
                        "Falling back to plain completion for this and all "
                        "subsequent json_mode calls in this session.",
                        e.__class__.__name__,
                    )
                    _JSON_MODE_UNSUPPORTED_WARNED = True
                # fall through to normal call below

        response = await self.client.chat.completions.create(**request_args)
        self._record_usage(getattr(response, "usage", None))
        return response.choices[0].message.content

    async def generate_structured(
        self,
        prompt: str,
        system_message: str | None = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generate structured JSON output.

        Always appends a prompt-level "respond with JSON only" instruction
        so we still get JSON when the gateway rejects ``response_format``.
        """
        json_instruction = (
            "\n\nIMPORTANT: Respond with valid JSON only. No markdown, no explanation."
        )
        prompt_with_instruction = prompt + json_instruction

        response_text = await self.generate(
            prompt_with_instruction,
            system_message=system_message,
            json_mode=True,
            **kwargs,
        )

        try:
            return parse_json(response_text)
        except ValueError:
            logger.error(
                "JSON parsing failed. Response text (first 500 chars): %s",
                (response_text or "")[:500],
            )
            raise

    async def generate_with_tools(
        self,
        prompt: str,
        system_message: str | None,
        tools: List[Dict[str, Any]],
        tool_dispatcher: Callable[[str, Dict[str, Any]], Dict[str, Any]],
        max_iterations: int = 4,
        **kwargs,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Run a tool-use loop and return the model's final text response
        plus a transcript of every tool call.

        The loop runs at most ``max_iterations`` rounds: each round either
        produces a final assistant message (no tool_calls) — at which
        point we return — or a batch of tool_calls, which we dispatch and
        feed back to the model.  If the loop hits the iteration cap we
        force a final answer by running one more call without ``tools``.

        Args:
            prompt: User prompt string.
            system_message: Optional system message (the architecture
                system prompt lives here).
            tools: List of OpenAI tool-spec dicts (see
                :mod:`app.core.tools`).
            tool_dispatcher: Callable ``(name, args_dict) -> result_dict``
                used to execute each tool. Should be fast / non-blocking.
            max_iterations: Hard cap on tool-call rounds. Prevents
                runaway loops if the model gets stuck.
            **kwargs: Forwarded as request args (temperature, max_tokens).

        Returns:
            ``(final_text, tool_calls_made)`` where ``tool_calls_made`` is
            a list of ``{"name": ..., "args": {...}, "result": {...}}``
            entries in call order.
        """
        messages: List[Dict[str, Any]] = self._build_messages(prompt, system_message)
        tool_calls_made: List[Dict[str, Any]] = []

        temperature = kwargs.get("temperature", settings.temperature)
        max_tokens = kwargs.get("max_tokens", settings.max_tokens)

        for iteration in range(max_iterations):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice="auto",
            )
            self._record_usage(getattr(response, "usage", None))

            assistant_msg = response.choices[0].message
            requested_calls = getattr(assistant_msg, "tool_calls", None) or []

            if not requested_calls:
                # Model produced a final answer — we're done.
                return assistant_msg.content or "", tool_calls_made

            # Echo the assistant tool-call message back into the conversation
            # exactly as the API requires, then append one ``tool`` role
            # message per executed call.
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in requested_calls
                    ],
                }
            )

            for tc in requested_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = tool_dispatcher(name, args)
                tool_calls_made.append({"name": name, "args": args, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    }
                )

            logger.info(
                "tool-use round %d: executed %d call(s) (%s)",
                iteration + 1,
                len(requested_calls),
                ", ".join(tc.function.name for tc in requested_calls),
            )

        # Cap exhausted — force a final answer with tools disabled.
        logger.warning(
            "Tool loop hit max_iterations=%d; forcing final answer.", max_iterations
        )
        final = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._record_usage(getattr(final, "usage", None))
        return final.choices[0].message.content or "", tool_calls_made

    async def generate_streaming(
        self,
        prompt: str,
        system_message: str | None = None,
        **kwargs,
    ):
        """
        Stream a text completion as chunks.

        Yields strings (one per delta). We ask the provider to include
        usage in the terminal stream chunk via ``stream_options`` so the
        per-instance counters stay accurate; gateways that ignore that
        flag just leave the counters unchanged for this call.
        """
        messages = self._build_messages(prompt, system_message)

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", settings.temperature),
            max_tokens=kwargs.get("max_tokens", settings.max_tokens),
            stream=True,
            stream_options={"include_usage": True},
        )

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                self._record_usage(usage)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is not None and delta.content is not None:
                yield delta.content

    async def close(self):
        await self.client.close()


class CachedLLMClient(LLMClient):
    """
    :class:`LLMClient` wrapper that consults a Redis cache before calling
    the API.  Cache hits skip the API and therefore correctly leave the
    per-instance usage counters at zero for that call.
    """

    def __init__(self, model: str | None = None, cache_manager: Optional[object] = None):
        super().__init__(model)
        self.cache_manager = cache_manager
        self.cache_enabled = settings.cache_llm_responses and cache_manager is not None

        if self.cache_enabled:
            logger.info("LLM response caching enabled")

    def _build_cache_key(
        self,
        prompt: str,
        system_message: str | None,
        **kwargs,
    ) -> tuple:
        return (
            self.model,
            system_message or "",
            prompt,
            kwargs.get("temperature", settings.temperature),
            kwargs.get("max_tokens", settings.max_tokens),
        )

    async def generate(
        self,
        prompt: str,
        system_message: str | None = None,
        **kwargs,
    ) -> str:
        if not self.cache_enabled:
            return await super().generate(prompt, system_message, **kwargs)

        cache_key = self._build_cache_key(prompt, system_message, **kwargs)
        cached = self.cache_manager.get_json(*cache_key)

        if cached is not None:
            logger.debug("LLM cache HIT for prompt: %s...", prompt[:50])
            return cached.get("content", "")

        logger.debug("LLM cache MISS for prompt: %s...", prompt[:50])
        content = await super().generate(prompt, system_message, **kwargs)

        self.cache_manager.set_json(
            {"content": content}, *cache_key, ttl=settings.cache_llm_ttl
        )
        return content

    async def generate_structured(
        self,
        prompt: str,
        system_message: str | None = None,
        **kwargs,
    ) -> Dict[str, Any]:
        if not self.cache_enabled:
            return await super().generate_structured(prompt, system_message, **kwargs)

        cache_key = self._build_cache_key(prompt, system_message, **kwargs)
        cached = self.cache_manager.get_json(*cache_key)

        if cached is not None:
            logger.debug("LLM structured cache HIT for prompt: %s...", prompt[:50])
            return cached.get("json_response", {})

        logger.debug("LLM structured cache MISS for prompt: %s...", prompt[:50])
        json_response = await super().generate_structured(prompt, system_message, **kwargs)

        self.cache_manager.set_json(
            {"json_response": json_response}, *cache_key, ttl=settings.cache_llm_ttl
        )
        return json_response
