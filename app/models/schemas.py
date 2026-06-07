"""
Pydantic schemas for strict API contracts and data validation
"""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# Core Request/Response Models
# ============================================================================

class SystemDesignQuery(BaseModel):
    """
    Request model for system design queries
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(
        ...,
        description="User's system design question or requirement",
        min_length=10,
        max_length=2000,
        examples=["Design a ride-sharing system like Uber"]
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID for conversation continuity. Auto-generated if not provided"
    )
    include_evaluation: bool = Field(
        default=True,
        description="Whether to include AI evaluation of the generated design"
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description="Additional context like scale requirements, constraints"
    )


class TradeOff(BaseModel):
    """
    Model representing architectural trade-offs
    """
    aspect: str = Field(..., description="The aspect being compared (e.g., 'Database Choice')")
    options: list[str] = Field(..., description="Available options", min_length=2)
    recommendation: str = Field(..., description="Recommended choice with reasoning")
    considerations: list[str] = Field(
        default_factory=list,
        description="Key considerations for this trade-off"
    )


class SystemArchitecture(BaseModel):
    """
    Structured system design architecture output
    Enforces strict JSON schema for LLM responses
    """
    services: list[str] = Field(
        ...,
        description="List of microservices/components",
        min_length=1,
        examples=[["API Gateway", "User Service", "Ride Service", "Matching Service"]]
    )
    database: str = Field(
        ...,
        description="Database architecture description",
        examples=["PostgreSQL for relational data + Redis for caching + Cassandra for ride history"]
    )
    scaling_strategy: str = Field(
        ...,
        description="Horizontal/vertical scaling approach",
        examples=["Horizontal scaling with load balancing and database sharding"]
    )
    tradeoffs: list[TradeOff] = Field(
        default_factory=list,
        description="Key architectural trade-offs and decisions"
    )
    key_components: dict[str, str] = Field(
        default_factory=dict,
        description="Detailed explanation of each component's role"
    )
    data_flow: str | None = Field(
        default=None,
        description="High-level description of data flow through the system"
    )
    api_design: list[str] = Field(
        default_factory=list,
        description="Key API endpoints or contracts"
    )
    non_functional_requirements: dict[str, str] = Field(
        default_factory=dict,
        description="How the design addresses NFRs (availability, consistency, latency, etc.)"
    )


class EvaluationResult(BaseModel):
    """
    AI evaluation of the generated system design
    """
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the design quality (0.0 - 1.0)"
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="Strengths of the proposed architecture"
    )
    weaknesses: list[str] = Field(
        default_factory=list,
        description="Potential weaknesses or gaps"
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Suggestions for improvement"
    )
    hallucination_check: bool = Field(
        default=True,
        description="Whether the response appears factually sound"
    )
    completeness_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="How complete the design is (0.0 - 1.0)"
    )


class TokenUsage(BaseModel):
    """
    Token usage tracking for cost monitoring
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class ToolCall(BaseModel):
    """
    Record of one LLM tool/function call made during architecture generation.
    """
    name: str = Field(..., description="Tool name as registered (e.g. 'estimate_capacity').")
    args: dict[str, Any] = Field(default_factory=dict, description="Arguments the model passed.")
    result: dict[str, Any] = Field(default_factory=dict, description="Tool result returned to the model.")


class ConfidenceMetrics(BaseModel):
    """
    Confidence metrics for RAG response quality
    """
    overall_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence score (0.0 - 1.0)"
    )
    confidence_level: str = Field(
        ...,
        description="Confidence level (HIGH, MEDIUM, LOW, VERY_LOW)"
    )
    retrieval_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence based on retrieval quality"
    )
    coverage_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence based on query coverage"
    )
    num_docs_retrieved: int = Field(..., description="Number of documents retrieved")
    avg_similarity_score: float = Field(..., description="Average similarity score of retrieved docs")
    recommendation: str = Field(..., description="Recommendation based on confidence")


class SystemDesignResponse(BaseModel):
    """
    Response model containing the complete system design
    """
    query: str = Field(..., description="Original user query")
    session_id: str = Field(..., description="Session ID for this conversation")
    architecture: SystemArchitecture | None = Field(
        default=None,
        description="Structured architecture design (None if insufficient knowledge)"
    )
    explanation: str = Field(..., description="Detailed explanation of the design")
    evaluation: EvaluationResult | None = Field(
        default=None,
        description="AI evaluation result if requested"
    )
    token_usage: TokenUsage | None = Field(
        default=None,
        description="Token usage for this request"
    )
    retrieved_context: list[str] = Field(
        default_factory=list,
        description="Retrieved document chunks used for RAG"
    )
    confidence_metrics: ConfidenceMetrics | None = Field(
        default=None,
        description="Confidence metrics for response quality"
    )
    insufficient_knowledge: bool = Field(
        default=False,
        description="True if hallucination guard blocked generation due to insufficient knowledge"
    )
    knowledge_gap_details: dict[str, Any] | None = Field(
        default=None,
        description="Details about why knowledge was insufficient (when insufficient_knowledge=True)"
    )
    confidence_warning: str | None = Field(
        default=None,
        description="Warning message for medium-confidence responses (0.3-0.6 range)"
    )
    degraded_mode: bool = Field(
        default=False,
        description="True when confidence was low but we still generated using related patterns as inspiration"
    )
    related_patterns: list[str] = Field(
        default_factory=list,
        description="Topic names used as fallback reference patterns when in degraded mode"
    )
    revision_count: int = Field(
        default=0,
        description="Number of reflection/revise passes performed (0 = first-shot design)"
    )
    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="LLM tool/function calls executed during generation (e.g. capacity estimates)."
    )
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================================================
# Conversation Management Models
# ============================================================================

class ConversationMessage(BaseModel):
    """
    Single message in a conversation
    """
    role: Literal["user", "assistant", "system"] = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationHistory(BaseModel):
    """
    Complete conversation history for a session
    """
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    messages: list[ConversationMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_message(self, role: Literal["user", "assistant", "system"], content: str) -> None:
        """Add a message to the conversation history"""
        self.messages.append(ConversationMessage(role=role, content=content))
        self.updated_at = datetime.now()

    def get_messages_for_prompt(self, max_messages: int = 10) -> list[dict[str, str]]:
        """Get recent messages formatted for LLM prompt"""
        recent_messages = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        return [{"role": msg.role, "content": msg.content} for msg in recent_messages]
