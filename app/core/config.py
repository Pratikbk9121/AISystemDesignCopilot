"""
Application configuration management using Pydantic Settings
"""
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application Settings
    app_name: str = "AI System Design Copilot"
    app_version: str = "0.1.0"
    debug: bool = False

    # API Settings
    api_v1_prefix: str = "/api/v1"

    # CORS Settings - allowed frontend origins
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        alias="CORS_ALLOWED_ORIGINS"
    )

    # Tekion LLM Gateway (Bifrost) Settings
    tekion_llm_key: str | None = Field(default=None, alias="TEKION_LLM_KEY")
    bifrost_base_url: str = Field(
        default="https://bifrost.stageapp.tekioncloud.xyz/v1",
        alias="BIFROST_BASE_URL"
    )
    embeddings_base_url: str = Field(
        default="https://bifrost.stageapp.tekioncloud.xyz/v1",
        alias="EMBEDDINGS_BASE_URL"
    )

    # Model Configuration
    model: str = "gpt-4.1-mini"  # Model available through Bifrost
    embedding_model: str = "text-embedding-3-small"
    max_tokens: int = 4096
    temperature: float = 0.7

    # Embedding Provider Configuration
    embedding_provider: str = "huggingface"  # Options: "huggingface", "openai"

    # HuggingFace Embedding Models (when embedding_provider = "huggingface")
    # Options:
    # - "sentence-transformers/all-MiniLM-L6-v2" (384 dim, fast, lightweight)
    # - "sentence-transformers/all-mpnet-base-v2" (768 dim, better quality)
    # - "BAAI/bge-small-en-v1.5" (384 dim, excellent performance)
    # - "BAAI/bge-base-en-v1.5" (768 dim, best quality - RECOMMENDED)
    huggingface_model: str = "BAAI/bge-base-en-v1.5"
    huggingface_model_kwargs: dict = {"device": "cpu"}  # Use "cuda" for GPU
    huggingface_encode_kwargs: dict = {"normalize_embeddings": True}

    # RAG Settings - Qdrant Vector Database
    qdrant_url: str = "http://localhost:6333"  # Qdrant server URL
    qdrant_collection_name: str = "system_design_docs"
    qdrant_use_memory: bool = True  # True for in-memory, False for persistent
    qdrant_path: str = "./data/vector_store/qdrant_data"  # Path for persistent storage

    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k_retrieval: int = 5

    # Advanced RAG Performance Settings
    # These settings control expensive RAG features that impact latency
    enable_multi_query_retrieval: bool = True  # ✅ ENABLED - Now uses fast heuristics (Task 2)
    multi_query_use_llm: bool = False  # ✅ Use fast heuristics, NOT slow LLM
    enable_reranking: bool = True  # Fast local reranking (minimal latency)
    enable_hallucination_guard: bool = True  # Fast local check (minimal latency)
    multi_query_num_sub_queries: int = 3  # Number of sub-queries if enabled
    multi_query_top_k_per_query: int = 3  # Documents per sub-query if enabled

    # Redis Cache Settings
    redis_enabled: bool = True  # ✅ ENABLED - Persistent caching for embeddings and LLM responses
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None  # For Redis Cloud
    redis_db: int = 0
    redis_ttl: int = 3600  # Default TTL: 1 hour

    # Cache-specific TTLs (in seconds)
    cache_embedding_ttl: int = 604800  # 7 days - embeddings are stable
    cache_llm_ttl: int = 3600  # 1 hour - query-specific responses
    cache_conversation_ttl: int = 1800  # 30 minutes - active sessions

    # Cache enable/disable per type
    cache_embeddings: bool = True
    cache_llm_responses: bool = True
    cache_conversations: bool = True

    # Retry & Timeout Settings
    llm_timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0

    # Token Usage Tracking
    track_token_usage: bool = True

    # Evaluation Settings
    enable_evaluation: bool = False  # ✅ DISABLED by default - Saves 3-7s (opt-in via request param)
    confidence_threshold: float = 0.7

    # Reflection / revise-loop settings
    # When evaluator confidence falls below the threshold the graph routes
    # generated → evaluate → revise → evaluate (up to max_revisions extra passes).
    reflection_enabled: bool = Field(default=True, alias="REFLECTION_ENABLED")
    reflection_confidence_threshold: float = Field(
        default=0.7, alias="REFLECTION_CONFIDENCE_THRESHOLD"
    )
    max_revisions: int = Field(default=2, alias="MAX_REVISIONS")

    # Function-calling / tool-use settings
    # When enabled, the architecture-generation pass receives the registered
    # tools (see app.core.tools) and may call them (e.g. estimate_capacity)
    # before producing the final JSON design.
    tools_enabled: bool = Field(default=True, alias="TOOLS_ENABLED")
    tool_max_iterations: int = Field(default=4, alias="TOOL_MAX_ITERATIONS")

    # Logging Settings
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_format: str = "json"  # "json" or "text"
    log_file: str | None = None  # Path to log file (None = stdout only)
    log_requests: bool = True  # Log all API requests
    log_errors: bool = True  # Log all errors

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the allowed values"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        """Validate log format is one of the allowed values"""
        valid_formats = ["json", "text"]
        if v.lower() not in valid_formats:
            raise ValueError(f"log_format must be one of {valid_formats}")
        return v.lower()

    @field_validator("embedding_provider")
    @classmethod
    def validate_embedding_provider(cls, v: str) -> str:
        """Validate embedding provider"""
        valid_providers = ["huggingface", "openai"]
        if v.lower() not in valid_providers:
            raise ValueError(f"embedding_provider must be one of {valid_providers}")
        return v.lower()


# Global settings instance
settings = Settings()
