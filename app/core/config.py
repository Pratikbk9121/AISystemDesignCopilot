"""
Application configuration management using Pydantic Settings
"""
from typing import Literal
from pydantic import Field
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
    
    # LLM Provider Settings
    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    
    # Model Configuration
    openai_model: str = "gpt-4-turbo-preview"
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    embedding_model: str = "text-embedding-3-small"
    max_tokens: int = 4096
    temperature: float = 0.7
    
    # RAG Settings
    vector_db_type: Literal["faiss", "pinecone"] = "faiss"
    faiss_index_path: str = "./data/vector_store/faiss_index"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k_retrieval: int = 5
    
    # Redis Cache Settings
    redis_enabled: bool = False
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_ttl: int = 3600  # 1 hour cache TTL
    
    # Retry & Timeout Settings
    llm_timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0
    
    # Token Usage Tracking
    track_token_usage: bool = True
    
    # Evaluation Settings
    enable_evaluation: bool = True
    confidence_threshold: float = 0.7


# Global settings instance
settings = Settings()
