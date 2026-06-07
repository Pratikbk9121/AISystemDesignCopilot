"""
System Design Orchestrator - The Brain

Deep module that owns the complete "Design Generation with Session Continuity" flow.

Interface (what callers see):
    response = await orchestrator.generate_design(query=SystemDesignQuery)

Implementation (what callers don't see):
    - Session ID generation
    - Conversation history loading/saving
    - Previous architecture extraction
    - Workflow execution
    - Response packaging
    - Metadata management

All session and state management complexity is hidden behind this seam.
"""
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from app.models.schemas import (
    SystemDesignQuery,
    SystemDesignResponse,
    ConversationHistory,
    SystemArchitecture,
    TradeOff,
    EvaluationResult,
    ConfidenceMetrics,
    TokenUsage,
    ToolCall,
)
from app.core.graph import SystemDesignGraph
from app.core.config import settings
from app.core.dependencies import get_llm_cache, get_conversation_cache
from app.core.state_manager import create_state_manager

logger = logging.getLogger(__name__)


class SystemDesignOrchestrator:
    """
    Deep module that owns complete Design Generation with Session Continuity.

    This module provides high leverage - callers get:
    - Session management (load/save conversation history)
    - Architecture generation (via workflow pipeline)
    - Response packaging (state dict → typed response objects)

    All in one call. No need to manage sessions, state, or response building.
    """

    def __init__(self):
        """Initialize orchestrator with workflow pipeline and state manager"""
        # Get dependencies
        llm_cache = get_llm_cache()
        conversation_cache = get_conversation_cache()

        # Initialize workflow pipeline
        self.graph = SystemDesignGraph(llm_cache_manager=llm_cache)

        # Initialize state manager (owns conversation persistence)
        self.state_manager = create_state_manager(conversation_cache)
    
    async def generate_design(
        self,
        query: SystemDesignQuery,
    ) -> SystemDesignResponse:
        """
        Deep interface for Design Generation with Session Continuity.

        This single method provides high leverage:
        - Handles session ID generation
        - Loads conversation history
        - Extracts previous architecture
        - Runs workflow pipeline
        - Packages response
        - Saves conversation state

        Callers just provide the query and get back a complete response.
        All session/state complexity is hidden.

        Args:
            query: SystemDesignQuery with user's question and optional session context

        Returns:
            SystemDesignResponse with complete architecture
        """
        # Step 1: Session management - generate or use existing session ID
        session_id = query.session_id or str(uuid4())

        # Step 2: Load conversation history
        conversation_history = await self.state_manager.get_conversation(session_id)

        # Step 3: Add user query to conversation
        conversation_history.add_message("user", query.query)

        # Step 4: Extract previous architecture from conversation metadata
        messages = conversation_history.get_messages_for_prompt()
        previous_architecture = conversation_history.metadata.get("last_architecture")

        # Step 5: Run workflow pipeline
        final_state = await self.graph.run(
            query=query.query,
            session_id=session_id,
            messages=messages,
            additional_context=query.context,
            include_evaluation=query.include_evaluation,
            previous_architecture=previous_architecture,
        )

        # Check for errors
        if final_state.get("error"):
            raise RuntimeError(f"Design generation failed: {final_state['error']}")

        # Token usage is captured by the finalize node of the graph.
        token_usage_data = final_state.get("token_usage")
        token_usage = TokenUsage(**token_usage_data) if token_usage_data else None

        # Check if hallucination guard was triggered
        if final_state.get("hallucination_guard_triggered", False):
            insufficient_response = final_state.get("insufficient_context_response", {})

            confidence_metrics_data = final_state.get("confidence_metrics", {})
            confidence_metrics = ConfidenceMetrics(**confidence_metrics_data) if confidence_metrics_data else None

            # Build knowledge gap details
            knowledge_gap_details = {
                "message": insufficient_response.get("message", "Not enough data"),
                "reason": insufficient_response.get("validation_details", {}).get("reason", "Insufficient context"),
                "suggestion": insufficient_response.get("validation_details", {}).get("suggestion", "Try adding more documentation"),
                "confidence_score": confidence_metrics.overall_confidence if confidence_metrics else 0.0,
                "retrieved_document_count": len(final_state.get("retrieved_documents", [])),
            }

            # Save conversation even when guard triggers
            explanation_text = insufficient_response.get("explanation", "Not enough data to answer your question")
            conversation_history.add_message("assistant", explanation_text)
            await self.state_manager.save_conversation(session_id, conversation_history)

            return SystemDesignResponse(
                query=query.query,
                session_id=session_id,
                architecture=None,  # No architecture when knowledge is insufficient
                explanation=explanation_text,
                evaluation=None,
                token_usage=token_usage,
                retrieved_context=[],
                confidence_metrics=confidence_metrics,
                insufficient_knowledge=True,
                knowledge_gap_details=knowledge_gap_details,
            )

        # Parse the results from state
        architecture = SystemArchitecture(**final_state["architecture_json"])
        explanation = final_state.get("explanation", "")

        # Parse evaluation if present
        evaluation = None
        if final_state.get("evaluation_json"):
            evaluation = EvaluationResult(**final_state["evaluation_json"])

        # Get retrieved context
        retrieved_context = final_state.get("retrieved_documents", [])

        # Get confidence metrics
        confidence_metrics_data = final_state.get("confidence_metrics", {})
        confidence_metrics = ConfidenceMetrics(**confidence_metrics_data) if confidence_metrics_data else None

        # Degraded mode (guard didn't hard-refuse but confidence is in the
        # extrapolation band). Take precedence over the generic medium-
        # confidence warning since the message is more specific.
        degraded_context = bool(final_state.get("degraded_context", False))
        related_patterns = list(final_state.get("related_patterns") or [])

        confidence_warning = None
        if degraded_context:
            related_str = ", ".join(related_patterns) if related_patterns else "no exact matches"
            confidence_warning = (
                f"⚠️ Limited Match: This design is extrapolated from related "
                f"reference patterns ({related_str}). Treat it as a starting "
                f"point and validate against authoritative sources."
            )
        elif confidence_metrics:
            # Check for medium confidence (0.3-0.6) and add warning
            conf_score = confidence_metrics.overall_confidence
            if 0.3 <= conf_score < 0.6:
                confidence_warning = (
                    f"⚠️ **Limited Knowledge Warning**: This design is based on medium confidence (score: {conf_score:.2f}). "
                    f"The system has limited knowledge about this specific architecture. "
                    f"Please validate this design against real-world production architectures, official documentation, "
                    f"and engineering blogs before implementation. Consider this a starting point for further research."
                )

        # Parse tool calls (any LLM function-calling invocations).
        tool_calls = [
            ToolCall(**tc) for tc in (final_state.get("tool_calls") or [])
        ]

        # Step 6: Build response
        response = SystemDesignResponse(
            query=query.query,
            session_id=session_id,
            architecture=architecture,
            explanation=explanation,
            evaluation=evaluation,
            token_usage=token_usage,
            retrieved_context=retrieved_context,
            confidence_metrics=confidence_metrics,
            confidence_warning=confidence_warning,
            degraded_mode=degraded_context,
            related_patterns=related_patterns,
            revision_count=int(final_state.get("revision_count", 0)),
            tool_calls=tool_calls,
        )

        # Step 7: Save conversation state (architecture + assistant message)
        conversation_history.metadata["last_architecture"] = architecture.model_dump(mode="json")
        conversation_history.add_message("assistant", explanation)
        await self.state_manager.save_conversation(session_id, conversation_history)

        return response

    async def stream_design(
        self,
        query: SystemDesignQuery,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Streaming counterpart to generate_design().

        Symmetric with the sync seam: callers pass a SystemDesignQuery and
        get back the event stream. Session lifecycle, conversation
        hydration, and persistence all live here — the route only frames
        events as SSE.

        Yields the event vocabulary the frontend already understands:
            metadata, progress, tool_call, design_complete,
            revision_started, evaluation, done, error.

        Persistence runs in a finally block so a client disconnect still
        saves the user message and any architecture captured before the
        stream was cut.
        """
        session_id = query.session_id or str(uuid4())
        history = await self.state_manager.get_conversation(session_id)
        history.add_message("user", query.query)

        captured_architecture: Dict[str, Any] | None = None
        captured_explanation: str = ""
        captured_revision_count: int = 0
        saw_error: bool = False
        # Parity with the sync path: surface degraded-mode signals and
        # the full insufficient-knowledge payload to streaming consumers.
        captured_degraded_mode: bool = False
        captured_related_patterns: List[str] = []
        captured_insufficient: Optional[Dict[str, Any]] = None

        yield {
            "type": "metadata",
            "data": {"session_id": session_id, "query": query.query},
        }

        try:
            async for event in self.graph.run_streaming(
                query=query.query,
                session_id=session_id,
                messages=history.get_messages_for_prompt(),
                additional_context=query.context,
                include_evaluation=query.include_evaluation,
                previous_architecture=history.metadata.get("last_architecture"),
            ):
                etype = event.get("type")
                edata = event.get("data") or {}
                if etype == "design_complete":
                    # revise_design fires another design_complete after the
                    # initial one — latest wins.
                    if edata.get("architecture"):
                        captured_architecture = edata["architecture"]
                    if edata.get("explanation"):
                        captured_explanation = edata["explanation"]
                    if "revision_count" in edata:
                        captured_revision_count = edata["revision_count"]
                elif etype == "degraded":
                    captured_degraded_mode = True
                    captured_related_patterns = list(
                        edata.get("related_patterns") or []
                    )
                elif etype == "insufficient_knowledge":
                    # User-data condition (not a system error), but it is
                    # terminal for this run — suppress the trailing `done`
                    # the same way we do for real errors so the frontend
                    # parser treats it as the end of stream.
                    captured_insufficient = dict(edata)
                    saw_error = True
                elif etype == "error":
                    saw_error = True
                yield event
        finally:
            try:
                if captured_architecture is not None:
                    history.metadata["last_architecture"] = captured_architecture
                if captured_explanation:
                    history.add_message("assistant", captured_explanation)
                elif captured_insufficient is not None:
                    # Mirror the sync path: when the hallucination guard
                    # fires there is no architecture/explanation, but we
                    # still want the assistant's "not enough data" reply
                    # in the conversation history.
                    insufficient_explanation = (
                        captured_insufficient.get("explanation")
                        or captured_insufficient.get("message")
                        or "Not enough data to answer your question"
                    )
                    history.add_message("assistant", insufficient_explanation)
                await self.state_manager.save_conversation(session_id, history)
            except Exception:
                logger.exception("Failed to persist conversation after streaming")

        # Skip the trailing `done` after an error event — the frontend
        # parser treats `error` as terminal and would reject a subsequent
        # `done` with StreamSequenceError. The error event is the terminal
        # signal.
        if not saw_error:
            yield {
                "type": "done",
                "data": {
                    "session_id": session_id,
                    "had_error": saw_error,
                    "revision_count": captured_revision_count,
                    "degraded_mode": captured_degraded_mode,
                    "related_patterns": captured_related_patterns,
                },
            }
