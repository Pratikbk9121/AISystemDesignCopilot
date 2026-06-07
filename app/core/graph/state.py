"""
State definitions for the LangGraph system-design workflow.

``SystemDesignState`` is a ``TypedDict`` whose keys flow through the graph;
LangGraph merges per-node return dicts into the running state. The
``Annotated[..., add]`` on ``messages`` lets nodes append rather than
overwrite.
"""
from typing import Any, Dict, List, TypedDict, Annotated
from operator import add


class ConversationContext(TypedDict):
    """Context information for the conversation"""
    session_id: str
    query: str
    additional_context: Dict[str, Any]
    include_evaluation: bool


class SystemDesignState(TypedDict, total=False):
    """
    State object for the system design generation workflow.

    Marked ``total=False`` because LangGraph nodes return partial-state
    dicts; not every key has to be present on every transition.
    """
    # --- Input ---
    query: str
    session_id: str
    additional_context: Dict[str, Any]
    include_evaluation: bool

    # --- Conversation history (accumulated via reducer) ---
    messages: Annotated[List[Dict[str, str]], add]

    # --- RAG retrieval ---
    retrieved_documents: List[str]
    confidence_metrics: Dict[str, Any]
    hallucination_guard_triggered: bool
    insufficient_context_response: Dict[str, Any]
    # Degraded mode: low confidence but still generated (Perplexity-style
    # "best effort" UX). Labelled as extrapolated from related patterns.
    degraded_context: bool
    related_patterns: List[str]

    # --- Generated outputs ---
    architecture_json: Dict[str, Any] | None
    explanation: str | None
    evaluation_json: Dict[str, Any] | None

    # --- Reflection / revise loop ---
    revision_count: int
    should_revise: bool
    previous_evaluation: Dict[str, Any] | None

    # --- Token usage (filled in by the finalize node) ---
    token_usage: Dict[str, Any] | None

    # --- Tool calls made during generation (function-calling) ---
    tool_calls: List[Dict[str, Any]]

    # --- Metadata ---
    current_step: str
    error: str | None

    # --- Previous architecture (for refinement queries from prior turns) ---
    previous_architecture: Dict[str, Any] | None
    is_refinement: bool
