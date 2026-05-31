"""
Streaming-chunk tests for the design-generation path.

Covers the two seams that have to cooperate for /query-stream to emit
``design_chunk`` SSE events as the LLM produces tokens:

1. ``LLMClient.generate_structured_stream`` — invokes its ``on_chunk``
   callback per delta and returns the parsed JSON at the end.
2. ``SystemDesignGraph.run_streaming`` — forwards the per-token writes a
   node makes via ``get_stream_writer`` as standalone ``design_chunk``
   events, and they arrive before ``design_complete``.
"""
from __future__ import annotations

from typing import AsyncIterator, List
from unittest.mock import MagicMock

import pytest

from app.core.graph.graph import SystemDesignGraph
from app.core.llm.client import LLMClient
from app.core.rag.context_retrieval import RetrievalResult
from app.models.schemas import ConfidenceMetrics


ARCH_JSON = (
    '{"services": ["api", "db"], "database": "Postgres", '
    '"scaling_strategy": "shard", "tradeoffs": [], "key_components": {}, '
    '"explanation": "use base62"}'
)


# --------------------------------------------------------------------------- #
# LLMClient.generate_structured_stream
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generate_structured_stream_invokes_callback_per_token():
    """Chunks should be delivered to ``on_chunk`` as they arrive."""
    deltas = ['{"services":', ' ["api"], ', '"database": "pg"}']

    async def fake_stream(*_args, **_kwargs) -> AsyncIterator[str]:
        for d in deltas:
            yield d

    # Build a bare LLMClient instance without going through __init__ (skips
    # the Bifrost key / httpx wiring).
    client = LLMClient.__new__(LLMClient)
    client.model = "gpt-4o-mini"
    client.usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    client.estimated_cost_usd = 0.0
    client.generate_streaming = fake_stream  # type: ignore[assignment]

    received: List[str] = []
    result = await client.generate_structured_stream(
        prompt="design a thing",
        system_message="be helpful",
        on_chunk=received.append,
    )

    assert received == deltas, "every streamed delta must reach on_chunk"
    assert result == {"services": ["api"], "database": "pg"}


@pytest.mark.asyncio
async def test_generate_structured_stream_parses_assembled_json_without_callback():
    """on_chunk is optional; assembled text must still parse."""
    deltas = ['{"a": ', '1, "b": ', '[2, 3]}']

    async def fake_stream(*_args, **_kwargs) -> AsyncIterator[str]:
        for d in deltas:
            yield d

    client = LLMClient.__new__(LLMClient)
    client.model = "gpt-4o-mini"
    client.usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    client.estimated_cost_usd = 0.0
    client.generate_streaming = fake_stream  # type: ignore[assignment]

    result = await client.generate_structured_stream(
        prompt="anything", system_message=None, on_chunk=None
    )

    assert result == {"a": 1, "b": [2, 3]}


# --------------------------------------------------------------------------- #
# SystemDesignGraph.run_streaming
# --------------------------------------------------------------------------- #


def _make_graph(arch_chunks: List[str]) -> SystemDesignGraph:
    """Build a SystemDesignGraph with the network-touching dependencies stubbed."""
    graph = SystemDesignGraph.__new__(SystemDesignGraph)

    # --- LLM client that streams ``arch_chunks`` for design generation
    # and returns a canned evaluation JSON for everything else. ---
    llm = MagicMock(name="LLM")

    async def _streamed_design(prompt, system_message=None, on_chunk=None, **_kw):
        full = ""
        for c in arch_chunks:
            full += c
            if on_chunk is not None:
                on_chunk(c)
        from app.core.llm.parser import parse_json
        return parse_json(full)

    async def _eval(prompt, system_message=None, **_kw):
        return {
            "overall_score": 8.0,
            "confidence_score": 0.9,
            "scalability_score": 8,
            "reliability_score": 8,
            "cost_efficiency_score": 8,
            "complexity_score": 5,
            "strengths": [],
            "weaknesses": [],
            "suggestions": [],
        }

    llm.generate_structured_stream = _streamed_design
    llm.generate_structured = _eval

    from app.models.schemas import TokenUsage

    llm.get_token_usage = MagicMock(
        return_value=TokenUsage(
            prompt_tokens=0, completion_tokens=0, total_tokens=0, estimated_cost_usd=0.0
        )
    )
    graph.llm_client = llm

    # --- Context retrieval stub that returns clean, high-confidence context. ---
    retrieval = MagicMock(name="ContextRetrieval")

    async def _retrieve(**_kw):
        return RetrievalResult(
            patterns=["doc-a", "doc-b"],
            confidence=ConfidenceMetrics(
                overall_confidence=0.9,
                confidence_level="HIGH",
                retrieval_confidence=0.9,
                coverage_confidence=0.9,
                num_docs_retrieved=2,
                avg_similarity_score=0.85,
                recommendation="proceed",
            ),
            guard_triggered=False,
            insufficient_response={},
        )

    retrieval.retrieve = _retrieve
    graph.context_retrieval = retrieval

    # --- Intent detector: simple NEW_DESIGN. ---
    from app.core.intent_detector import Intent

    intent = MagicMock(name="IntentDetector")
    intent.detect = MagicMock(return_value=Intent.NEW_DESIGN)
    graph.intent_detector = intent

    # --- Real prompts + parser; they're pure-Python. ---
    from app.core.llm.prompts import PromptTemplates
    from app.core.llm.parser import StructuredOutputParser

    graph.prompts = PromptTemplates()
    graph.parser = StructuredOutputParser()

    graph.compiled = graph._build_graph()
    return graph


@pytest.mark.asyncio
async def test_run_streaming_emits_design_chunks_before_design_complete(monkeypatch):
    """The frontend's incremental parser relies on chunks arriving early."""
    # Force the non-tools path; the tools branch intentionally buffers.
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "tools_enabled", False)

    chunks = ['{"services": ["api"], ', '"database": "pg", ', '"scaling_strategy": "shard"}']
    graph = _make_graph(chunks)

    events = []
    async for evt in graph.run_streaming(
        query="Design a URL shortener",
        session_id="sess-1",
        messages=[],
        additional_context=None,
        include_evaluation=False,
        previous_architecture=None,
    ):
        events.append(evt)

    chunk_events = [e for e in events if e["type"] == "design_chunk"]
    assert [e["data"]["chunk"] for e in chunk_events] == chunks, (
        "each LLM delta must surface as its own design_chunk event"
    )

    types = [e["type"] for e in events]
    assert types.count("design_complete") == 1
    # Every chunk must land before design_complete — that's the whole point
    # of streaming for the IncrementalArchitectureParser.
    last_chunk_idx = max(i for i, e in enumerate(events) if e["type"] == "design_chunk")
    complete_idx = next(i for i, e in enumerate(events) if e["type"] == "design_complete")
    assert last_chunk_idx < complete_idx

    complete = events[complete_idx]
    assert complete["data"]["architecture"]["services"] == ["api"]
