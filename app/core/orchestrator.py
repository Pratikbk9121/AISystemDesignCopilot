"""
System Design Orchestrator - The Brain
Coordinates RAG retrieval, prompt construction, and LLM generation using LangGraph
"""
from typing import Any, Dict

from app.models.schemas import (
    SystemDesignResponse,
    ConversationHistory,
    SystemArchitecture,
    TradeOff,
    EvaluationResult,
    TokenUsage,
)
from app.core.graph import SystemDesignGraph
from app.core.config import settings


class SystemDesignOrchestrator:
    """
    Main orchestrator that coordinates all components using LangGraph.

    Workflow (powered by LangGraph):
    1. RAG retrieval from vector database
    2. Intent detection (new design vs refinement)
    3. Dynamic prompt construction
    4. LLM generation with structured outputs
    5. Optional evaluation
    6. Response packaging
    """

    def __init__(self):
        """Initialize the orchestrator with LangGraph workflow"""
        self.graph = SystemDesignGraph()
    
    async def generate_design(
        self,
        query: str,
        session_id: str,
        conversation_history: ConversationHistory,
        include_evaluation: bool = True,
        context: Dict[str, Any] | None = None,
    ) -> SystemDesignResponse:
        """
        Generate a system design based on the user's query using LangGraph workflow.

        Args:
            query: User's system design question
            session_id: Session identifier
            conversation_history: Previous conversation context
            include_evaluation: Whether to evaluate the design
            context: Additional context from the user

        Returns:
            SystemDesignResponse with complete architecture
        """
        # Get previous messages for context
        messages = conversation_history.get_messages_for_prompt()

        # Extract previous architecture if exists
        previous_architecture = None
        if messages and len(messages) > 0:
            # Try to get the last generated architecture from metadata
            previous_architecture = conversation_history.metadata.get("last_architecture")

        # Run the LangGraph workflow
        final_state = await self.graph.run(
            query=query,
            session_id=session_id,
            messages=messages,
            additional_context=context,
            include_evaluation=include_evaluation,
            previous_architecture=previous_architecture,
        )

        # Check for errors
        if final_state.get("error"):
            raise RuntimeError(f"Design generation failed: {final_state['error']}")

        # Parse the results from state
        architecture = SystemArchitecture(**final_state["architecture_json"])
        explanation = final_state.get("explanation", "")

        # Parse evaluation if present
        evaluation = None
        if final_state.get("evaluation_json"):
            evaluation = EvaluationResult(**final_state["evaluation_json"])

        # Extract token usage (if available)
        token_usage_data = final_state.get("token_usage", {})
        token_usage = TokenUsage(
            prompt_tokens=token_usage_data.get("prompt_tokens", 0),
            completion_tokens=token_usage_data.get("completion_tokens", 0),
            total_tokens=token_usage_data.get("total_tokens", 0),
            estimated_cost_usd=token_usage_data.get("estimated_cost_usd", 0.0),
        )

        # Get retrieved context
        retrieved_context = final_state.get("retrieved_documents", [])

        # Build response
        response = SystemDesignResponse(
            query=query,
            session_id=session_id,
            architecture=architecture,
            explanation=explanation,
            evaluation=evaluation,
            token_usage=token_usage,
            retrieved_context=retrieved_context,
        )

        # Store architecture in conversation metadata for future refinement
        conversation_history.metadata["last_architecture"] = architecture.dict()

        return response
