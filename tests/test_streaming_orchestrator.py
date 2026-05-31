"""
Integration tests for SystemDesignOrchestrator.stream_design().

The orchestrator owns the session lifecycle; these tests assert that
behaviour by scripting graph events and inspecting the in-memory state
manager after the stream is drained.
"""
import asyncio

import pytest

from app.core.orchestrator import SystemDesignOrchestrator
from app.core.state_manager import ConversationStateManager
from app.models.schemas import SystemDesignQuery


ARCH_V1 = {
    "services": ["api", "db"],
    "database": "Postgres",
    "scaling_strategy": "Horizontal sharding",
    "tradeoffs": [],
    "key_components": {},
}
ARCH_V2 = {
    "services": ["api", "db", "cache"],
    "database": "Postgres + Redis",
    "scaling_strategy": "Horizontal sharding plus read replicas",
    "tradeoffs": [],
    "key_components": {},
}


class _FakeGraph:
    """Captures kwargs and yields a scripted (or callable) event sequence."""

    def __init__(self, scripted_events):
        self._scripted = scripted_events
        self.calls = []

    async def run_streaming(self, **kwargs):
        self.calls.append(kwargs)
        if callable(self._scripted):
            async for event in self._scripted(**kwargs):
                yield event
            return
        for event in self._scripted:
            yield event


def _make_orchestrator(scripted_events):
    orchestrator = SystemDesignOrchestrator.__new__(SystemDesignOrchestrator)
    orchestrator.state_manager = ConversationStateManager()
    orchestrator.graph = _FakeGraph(scripted_events)
    return orchestrator


def _script(orchestrator, scripted_events):
    """Swap the graph script while preserving the same state manager."""
    orchestrator.graph = _FakeGraph(scripted_events)


def _query(text="Design a URL shortener", session_id=None):
    return SystemDesignQuery(query=text, session_id=session_id, include_evaluation=True)


async def _drain(async_iter):
    return [event async for event in async_iter]


@pytest.mark.asyncio
async def test_stream_design_success_path_persists_architecture():
    events = [
        {"type": "progress", "data": {"step": "rag_complete", "message": "ok"}},
        {"type": "progress", "data": {"step": "intent_detected", "is_refinement": False}},
        {"type": "design_complete", "data": {
            "architecture": ARCH_V1,
            "explanation": "Use a hash table and a base62 encoder.",
            "tool_calls": [],
        }},
        {"type": "evaluation", "data": {"confidence_score": 0.8}},
        {"type": "progress", "data": {"step": "finalize", "token_usage": {"total_tokens": 100}}},
    ]
    orch = _make_orchestrator(events)

    yielded = await _drain(orch.stream_design(_query()))

    assert yielded[0]["type"] == "metadata"
    session_id = yielded[0]["data"]["session_id"]
    assert session_id  # uuid generated

    forwarded = [e["type"] for e in yielded[1:-1]]
    assert forwarded == [
        "progress", "progress", "design_complete", "evaluation", "progress",
    ]

    assert yielded[-1]["type"] == "done"
    assert yielded[-1]["data"]["session_id"] == session_id
    assert yielded[-1]["data"]["had_error"] is False

    history = await orch.state_manager.get_conversation(session_id)
    assert history.metadata["last_architecture"] == ARCH_V1
    assert [m.role for m in history.messages] == ["user", "assistant"]
    assert history.messages[-1].content == "Use a hash table and a base62 encoder."


@pytest.mark.asyncio
async def test_stream_design_refinement_uses_previous_architecture():
    # First turn — captures ARCH_V1.
    first_events = [
        {"type": "design_complete", "data": {
            "architecture": ARCH_V1,
            "explanation": "v1",
        }},
    ]
    orch = _make_orchestrator(first_events)
    first_yielded = await _drain(orch.stream_design(_query("Design a URL shortener")))
    session_id = first_yielded[0]["data"]["session_id"]

    # Second turn — should see ARCH_V1 as previous_architecture, and the
    # later (revised) design_complete should overwrite last_architecture.
    second_events = [
        {"type": "design_complete", "data": {
            "architecture": ARCH_V1,
            "explanation": "v1 again",
            "revision_count": 0,
        }},
        {"type": "revision_started", "data": {"revision_count": 1}},
        {"type": "design_complete", "data": {
            "architecture": ARCH_V2,
            "explanation": "v2 with caching",
            "revision_count": 1,
        }},
    ]
    _script(orch, second_events)
    second_yielded = await _drain(
        orch.stream_design(_query("Add a Redis cache", session_id=session_id))
    )

    # Graph received the prior architecture on the second turn.
    assert orch.graph.calls[-1]["previous_architecture"] == ARCH_V1

    # The latest design_complete (revision) wins.
    history = await orch.state_manager.get_conversation(session_id)
    assert history.metadata["last_architecture"] == ARCH_V2
    # done event reports the revision count.
    assert second_yielded[-1]["data"]["revision_count"] == 1


@pytest.mark.asyncio
async def test_stream_design_client_disconnect_still_saves():
    """The orchestrator's try/finally must persist on GeneratorExit."""

    async def slow_stream(**_kwargs):
        # Yield the design_complete, then block until cancelled.
        yield {"type": "design_complete", "data": {
            "architecture": ARCH_V1,
            "explanation": "partial",
        }}
        await asyncio.sleep(60)  # caller will aclose() before this finishes

    orch = _make_orchestrator(slow_stream)

    gen = orch.stream_design(_query())

    # Drain up to and including design_complete, then drop the consumer.
    seen = []
    async for event in gen:
        seen.append(event)
        if event["type"] == "design_complete":
            break
    await gen.aclose()

    # Session id is from the metadata event.
    session_id = seen[0]["data"]["session_id"]
    history = await orch.state_manager.get_conversation(session_id)
    assert history.metadata["last_architecture"] == ARCH_V1
    assert any(m.role == "assistant" and m.content == "partial" for m in history.messages)


@pytest.mark.asyncio
async def test_stream_design_hallucination_guard_emits_error_and_skips_arch_save():
    events = [
        {"type": "error", "data": {
            "message": "Insufficient context to generate design",
            "step": "retrieve_context",
        }},
    ]
    orch = _make_orchestrator(events)

    yielded = await _drain(orch.stream_design(_query()))

    session_id = yielded[0]["data"]["session_id"]
    types = [e["type"] for e in yielded]
    assert types[0] == "metadata"
    # `error` is the terminal signal — no trailing `done` should follow
    # (the frontend SSE parser treats error as terminal and would reject
    # a subsequent done with StreamSequenceError).
    assert types[-1] == "error"
    assert "done" not in types

    history = await orch.state_manager.get_conversation(session_id)
    # No architecture captured -> metadata untouched.
    assert "last_architecture" not in history.metadata
    # No assistant message appended; the user message is still saved.
    assert [m.role for m in history.messages] == ["user"]
