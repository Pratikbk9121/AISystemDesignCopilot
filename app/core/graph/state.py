"""
State definitions for LangGraph system design workflow
"""
from typing import Any, Dict, List, Literal, TypedDict, Annotated
from operator import add


class ConversationContext(TypedDict):
    """Context information for the conversation"""
    session_id: str
    query: str
    additional_context: Dict[str, Any]
    include_evaluation: bool


class SystemDesignState(TypedDict):
    """
    State object for the system design generation workflow.
    LangGraph uses this to track state across nodes.
    """
    # Input
    query: str
    session_id: str
    additional_context: Dict[str, Any]
    include_evaluation: bool
    
    # Conversation history (accumulated)
    messages: Annotated[List[Dict[str, str]], add]
    
    # RAG retrieval
    retrieved_documents: List[str]
    
    # Generated outputs
    architecture_json: Dict[str, Any] | None
    explanation: str | None
    evaluation_json: Dict[str, Any] | None
    
    # Metadata
    current_step: str
    error: str | None
    token_usage: Dict[str, int]
    
    # Previous architecture (for refinement queries)
    previous_architecture: Dict[str, Any] | None
    is_refinement: bool
