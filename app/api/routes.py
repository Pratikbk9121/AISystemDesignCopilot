"""
API Routes for System Design endpoints

Thin HTTP adapters that delegate to deep business logic modules.
"""
import json
import json as _json
import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.orchestrator import SystemDesignOrchestrator
from app.core.dependencies import get_conversation_cache, get_vector_store
from app.core.state_manager import create_state_manager
from app.core.knowledge_analyzer import KnowledgeAnalyzer
from app.models.schemas import (
    SystemDesignQuery,
    SystemDesignResponse,
    ConversationHistory,
)

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/system-design", tags=["System Design"])


@router.post(
    "/query",
    response_model=SystemDesignResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate system design architecture",
    description="Generate a comprehensive system design based on the user's query with RAG-enhanced context"
)
async def generate_system_design(query: SystemDesignQuery) -> SystemDesignResponse:
    """
    Generate a system design architecture based on the user's query.

    This endpoint is now a thin HTTP adapter - all business logic lives in the
    deep SystemDesignOrchestrator module (session management, workflow execution,
    response packaging).

    Args:
        query: SystemDesignQuery containing the user's question and optional session context

    Returns:
        SystemDesignResponse with structured architecture, evaluation, and metadata

    Raises:
        HTTPException: 500 if generation fails
    """
    # Validate context size before invoking orchestrator
    if query.context and len(_json.dumps(query.context)) > 10_000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Context too large (max 10KB)"
        )

    try:
        # Log the request
        session_id = query.session_id or "(new session)"
        logger.info(f"Processing system design query for session: {session_id}")

        # Use deep orchestrator - single call with high leverage
        # Orchestrator handles: session management, workflow, response packaging
        orchestrator = SystemDesignOrchestrator()
        response = await orchestrator.generate_design(query=query)

        logger.info(f"Successfully generated design for session: {response.session_id}")
        return response

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to generate system design")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.post(
    "/query-stream",
    status_code=status.HTTP_200_OK,
    summary="Generate system design with streaming (FAST perceived latency)",
    description="Stream the system design generation process for better user experience. Returns Server-Sent Events (SSE)."
)
async def generate_system_design_stream(query: SystemDesignQuery):
    """
    Generate system design with STREAMING for faster perceived latency.

    This endpoint streams the design generation process using Server-Sent Events (SSE):
    1. Initial metadata (session_id, query)
    2. RAG context retrieval progress
    3. LLM design generation (streamed as it's generated)
    4. Evaluation (if requested, in background)

    **Perceived latency: ~300ms to first token** vs 8-15s for full response

    Args:
        query: SystemDesignQuery containing the user's question and optional session context

    Returns:
        StreamingResponse with Server-Sent Events

    Event types:
        - metadata: Initial session info
        - progress: RAG retrieval updates
        - design_chunk: Incremental design content
        - design_complete: Final architecture JSON
        - evaluation: Evaluation results (if requested)
        - done: Stream complete
        - error: Error occurred
    """
    # Validate context size before starting the stream
    if query.context and len(_json.dumps(query.context)) > 10_000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Context too large (max 10KB)"
        )

    async def event_generator():
        """Frame orchestrator events as Server-Sent Events."""
        try:
            orchestrator = SystemDesignOrchestrator()
            async for event in orchestrator.stream_design(query):
                event_type = event.get("type", "progress")
                event_data = json.dumps(event.get("data", {}))
                yield f"event: {event_type}\ndata: {event_data}\n\n"
        except Exception:
            logger.exception("[STREAM] Failed to generate system design")
            error_data = json.dumps({"detail": "Internal server error"})
            yield f"event: error\ndata: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.get(
    "/conversation/{session_id}",
    response_model=ConversationHistory,
    status_code=status.HTTP_200_OK,
    summary="Retrieve conversation history",
    description="Get the complete conversation history for a session"
)
async def get_conversation_history(session_id: str) -> ConversationHistory:
    """
    Retrieve the conversation history for a given session.

    Args:
        session_id: The session identifier

    Returns:
        ConversationHistory containing all messages in the session

    Raises:
        HTTPException: 404 if session not found
    """
    try:
        conversation_cache = get_conversation_cache()
        state_mgr = create_state_manager(conversation_cache)
        conversation = state_mgr.get_conversation(session_id)
        return conversation
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )


@router.delete(
    "/conversation/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear conversation history",
    description="Delete the conversation history for a session"
)
async def clear_conversation(session_id: str) -> None:
    """
    Clear the conversation history for a given session.

    Args:
        session_id: The session identifier

    Returns:
        None
    """
    conversation_cache = get_conversation_cache()
    state_mgr = create_state_manager(conversation_cache)
    state_mgr.delete_conversation(session_id)





@router.get(
    "/knowledge/topics",
    status_code=status.HTTP_200_OK,
    summary="Get available knowledge base topics",
    description="Returns information about system design topics available in the knowledge base"
)
async def get_knowledge_topics() -> dict:
    """
    Get list of available system design topics in the knowledge base.

    This helps users understand what queries are likely to succeed
    and what topics have comprehensive documentation.

    Returns:
        Dictionary with:
        - topics: List of available topics with metadata
        - document_count: Number of documents indexed
        - coverage_areas: Categories of system design patterns
        - example_queries: Example queries that would work well
    """
    try:
        vector_store = get_vector_store()
        analyzer = KnowledgeAnalyzer(vector_store=vector_store)
        topics_info = analyzer.get_available_topics()

        return {
            "status": "success",
            "data": topics_info
        }
    except Exception:
        logger.exception("Failed to get knowledge topics")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/knowledge/stats",
    status_code=status.HTTP_200_OK,
    summary="Get knowledge base statistics",
    description="Returns detailed statistics about the knowledge base"
)
async def get_knowledge_stats() -> dict:
    """
    Get detailed statistics about the knowledge base.

    Returns:
        Statistics including file counts, sizes, types, and categories
    """
    try:
        vector_store = get_vector_store()
        analyzer = KnowledgeAnalyzer(vector_store=vector_store)
        stats = analyzer.get_knowledge_stats()

        return {
            "status": "success",
            "data": stats
        }
    except Exception:
        logger.exception("Failed to get knowledge stats")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Check if the API is healthy and all dependencies are available"
)
async def health_check() -> dict[str, str]:
    """
    Health check endpoint to verify the API is running.

    Returns:
        dict with status information
    """
    return {
        "status": "healthy",
        "service": "AI System Design Copilot",
        "version": "0.1.0"
    }
