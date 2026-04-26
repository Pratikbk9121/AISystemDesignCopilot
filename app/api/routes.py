"""
API Routes for System Design endpoints
"""
from fastapi import APIRouter, HTTPException, status
from uuid import uuid4

from app.models.schemas import (
    SystemDesignQuery,
    SystemDesignResponse,
    ConversationHistory,
)
from app.core.orchestrator import SystemDesignOrchestrator
from app.core.state_manager import ConversationStateManager

# Initialize router
router = APIRouter(prefix="/system-design", tags=["System Design"])

# Initialize dependencies (will be replaced with proper dependency injection)
orchestrator = SystemDesignOrchestrator()
state_manager = ConversationStateManager()


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
    
    This endpoint:
    1. Retrieves relevant documentation from the vector database
    2. Constructs a context-rich prompt with conversation history
    3. Generates a structured system design using LLM
    4. Optionally evaluates the design for quality and completeness
    
    Args:
        query: SystemDesignQuery containing the user's question and optional session context
    
    Returns:
        SystemDesignResponse with structured architecture, evaluation, and metadata
    
    Raises:
        HTTPException: 500 if generation fails
    """
    try:
        # Generate or use existing session ID
        session_id = query.session_id or str(uuid4())
        
        # Get conversation history
        conversation_history = state_manager.get_conversation(session_id)
        
        # Add user query to history
        conversation_history.add_message("user", query.query)
        
        # Generate system design
        response = await orchestrator.generate_design(
            query=query.query,
            session_id=session_id,
            conversation_history=conversation_history,
            include_evaluation=query.include_evaluation,
            context=query.context,
        )
        
        # Save updated conversation history
        conversation_history.add_message("assistant", response.explanation)
        state_manager.save_conversation(session_id, conversation_history)
        
        return response
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate system design: {str(e)}"
        ) from e


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
        conversation = state_manager.get_conversation(session_id)
        return conversation
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
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
    state_manager.delete_conversation(session_id)


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
