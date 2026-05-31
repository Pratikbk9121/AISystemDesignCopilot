"""
Application configuration management using Pydantic Settings
"""
from pathlib import Path
from typing import Literal

from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CACHE_KEY_SALT_PLACEHOLDER = "replace-with-generated-token-at-least-16-chars"


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

    # Deployment environment — gates prod invariants.
    environment: Literal["dev", "staging", "prod"] = Field(
        default="dev", alias="ENVIRONMENT"
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

    # LLM provider selector. "bifrost" (default) uses Tekion's gateway with
    # the x-bf-vk header. "openai_compatible" uses any OpenAI-compatible
    # endpoint (Gemini OpenAI shim, Groq, Cerebras, OpenRouter, ...) with
    # standard Bearer auth — that's what the public deployment uses.
    llm_provider: Literal["bifrost", "openai_compatible"] = Field(
        default="bifrost", alias="LLM_PROVIDER"
    )

    # Tekion LLM Gateway (Bifrost) Settings.
    # Required only when llm_provider=="bifrost"; the model_validator below
    # enforces that. Default is the placeholder so an openai_compatible deploy
    # can boot without leaking a Bifrost key into env.
    tekion_llm_key: str = Field(default="", alias="TEKION_LLM_KEY")
    bifrost_base_url: str = Field(
        default="https://bifrost.stageapp.tekioncloud.xyz/v1",
        alias="BIFROST_BASE_URL"
    )
    embeddings_base_url: str = Field(
        default="https://bifrost.stageapp.tekioncloud.xyz/v1",
        alias="EMBEDDINGS_BASE_URL"
    )

    # Generic OpenAI-compatible provider settings. Used only when
    # llm_provider=="openai_compatible". Falls back to bifrost_* when unset
    # so callers can read via the effective_* properties unconditionally.
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")

    # Model Configuration
    model: str = "gpt-4.1-mini"  # Bifrost default; openai_compatible uses LLM_MODEL
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
    qdrant_path: str = Field(
        default="./data/vector_store/qdrant_data",
        alias="QDRANT_PATH",
    )

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

    # Salt used when hashing cache keys. Default is a non-secret placeholder so
    # dev/test boots without manual setup; the prod model-validator rejects the
    # placeholder so production deploys are forced to set a real value.
    cache_key_salt: str = Field(
        default=_CACHE_KEY_SALT_PLACEHOLDER,
        alias="CACHE_KEY_SALT",
        min_length=16,
    )

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

    # Auth + Rate Limiting
    # API keys are accepted via the `x-api-key` header. Provide as a
    # comma-separated string in env (e.g. `API_KEYS=key1,key2`); the validator
    # below splits and strips. `test_api_key` is an optional convenience for
    # eval harnesses and CI — it is also accepted as a valid `x-api-key`.
    # `NoDecode` tells pydantic-settings not to try JSON-parsing the env value;
    # the validator below splits on commas instead.
    api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="API_KEYS"
    )
    api_auth_enabled: bool = Field(default=True, alias="API_AUTH_ENABLED")
    test_api_key: str | None = Field(default=None, alias="TEST_API_KEY")

    rate_limit_default: str = Field(default="120/minute", alias="RATE_LIMIT_DEFAULT")
    rate_limit_query: str = Field(default="20/minute", alias="RATE_LIMIT_QUERY")
    rate_limit_health: str = Field(default="60/minute", alias="RATE_LIMIT_HEALTH")
    rate_limit_storage_uri: str = Field(
        default="memory://", alias="RATE_LIMIT_STORAGE_URI"
    )

    # Startup behavior
    # AUTO_SEED_KNOWLEDGE: when Qdrant collection is empty at boot, seed it from
    # KNOWLEDGE_DATA_DIR by calling bootstrap_knowledge(). Off by default so
    # production deploys don't quietly re-ingest on every restart.
    # QDRANT_REQUIRED_ON_STARTUP: when true, any Qdrant init failure kills the
    # process (uvicorn exits non-zero). Set to false on laptops without Qdrant
    # to run degraded.
    # BIFROST_HEALTHCHECK_ON_STARTUP: when true, the lifespan does a fast probe
    # of BIFROST_BASE_URL. In prod the boot fails if the probe says "down".
    # KNOWLEDGE_DATA_DIR: directory of .md/.txt/.json files passed to the
    # bootstrap_knowledge() ingestion path.
    auto_seed_knowledge: bool = Field(default=False, alias="AUTO_SEED_KNOWLEDGE")
    qdrant_required_on_startup: bool = Field(
        default=True, alias="QDRANT_REQUIRED_ON_STARTUP"
    )
    bifrost_healthcheck_on_startup: bool = Field(
        default=False, alias="BIFROST_HEALTHCHECK_ON_STARTUP"
    )
    knowledge_data_dir: str = Field(
        default="./data/system_design_docs", alias="KNOWLEDGE_DATA_DIR"
    )

    # Observability — /readyz, Prometheus /metrics, optional Sentry.
    readyz_check_bifrost: bool = Field(
        default=False, alias="READYZ_CHECK_BIFROST"
    )
    readyz_require_bifrost: bool = Field(
        default=False, alias="READYZ_REQUIRE_BIFROST"
    )
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    metrics_basic_auth_user: str | None = Field(
        default=None, alias="METRICS_BASIC_AUTH_USER"
    )
    metrics_basic_auth_password: str | None = Field(
        default=None, alias="METRICS_BASIC_AUTH_PASSWORD"
    )
    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    sentry_environment: str = Field(
        default="development", alias="SENTRY_ENVIRONMENT"
    )
    sentry_traces_sample_rate: float = Field(
        default=0.1, alias="SENTRY_TRACES_SAMPLE_RATE"
    )
    sentry_profiles_sample_rate: float = Field(
        default=0.0, alias="SENTRY_PROFILES_SAMPLE_RATE"
    )

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_api_keys(cls, v):
        """Accept comma-separated env string or list. Strip + drop empties."""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        if isinstance(v, list):
            return [str(k).strip() for k in v if str(k).strip()]
        return v

    @field_validator("tekion_llm_key")
    @classmethod
    def _reject_placeholder_llm_key(cls, v: str) -> str:
        # Allow empty: the openai_compatible provider path doesn't need a
        # Bifrost key. The model_validator enforces non-empty when
        # llm_provider=="bifrost".
        stripped = v.strip()
        if stripped.lower() in {"changeme", "your-key-here", "your-bifrost-key-here"}:
            raise ValueError("TEKION_LLM_KEY is still set to a placeholder value")
        return stripped

    @field_validator("qdrant_path", mode="after")
    @classmethod
    def _resolve_qdrant_path(cls, v: str) -> str:
        """Resolve relative qdrant paths against the repo root so containers
        and cron jobs don't depend on cwd. Absolute paths are returned as-is."""
        path = Path(v)
        if path.is_absolute():
            return str(path)
        return str((_REPO_ROOT / path).resolve())

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

    @model_validator(mode="after")
    def _enforce_llm_provider_requirements(self) -> "Settings":
        """Each provider has different mandatory inputs."""
        if self.llm_provider == "bifrost":
            if not self.tekion_llm_key:
                raise ValueError(
                    "LLM_PROVIDER=bifrost requires TEKION_LLM_KEY to be set."
                )
        else:  # openai_compatible
            missing = [
                n for n, v in (
                    ("LLM_BASE_URL", self.llm_base_url),
                    ("LLM_API_KEY", self.llm_api_key),
                ) if not v
            ]
            if missing:
                raise ValueError(
                    "LLM_PROVIDER=openai_compatible requires "
                    + ", ".join(missing)
                )
        return self

    @property
    def effective_llm_base_url(self) -> str:
        if self.llm_provider == "openai_compatible" and self.llm_base_url:
            return self.llm_base_url
        return self.bifrost_base_url

    @property
    def effective_llm_api_key(self) -> str:
        if self.llm_provider == "openai_compatible" and self.llm_api_key:
            return self.llm_api_key
        return self.tekion_llm_key

    @property
    def effective_llm_model(self) -> str:
        if self.llm_provider == "openai_compatible" and self.llm_model:
            return self.llm_model
        return self.model

    @model_validator(mode="after")
    def _enforce_prod_invariants(self) -> "Settings":
        """In prod, refuse to boot with dev-only defaults."""
        if self.environment != "prod":
            return self
        violations: list[str] = []
        if self.qdrant_use_memory:
            violations.append("QDRANT_USE_MEMORY must be false in prod")
        if self.redis_enabled and self.redis_host in {"localhost", "127.0.0.1", "::1"}:
            violations.append(
                f"REDIS_HOST cannot be {self.redis_host!r} in prod (REDIS_ENABLED=true)"
            )
        if self.debug:
            violations.append("DEBUG must be false in prod")
        if self.cache_key_salt == _CACHE_KEY_SALT_PLACEHOLDER:
            violations.append("CACHE_KEY_SALT must be set to a strong value in prod")
        if violations:
            raise ValueError(
                "Prod invariants violated:\n  - " + "\n  - ".join(violations)
            )
        return self

    @model_validator(mode="after")
    def _enforce_auth_configured(self) -> "Settings":
        """Refuse to boot with auth enabled but no keys configured.

        DEBUG=true is honored as an explicit dev opt-out so local boots without
        keys still work; otherwise an empty API_KEYS list with auth enabled is
        almost certainly a deployment misconfiguration.
        """
        if self.api_auth_enabled and not self.api_keys and not self.debug:
            raise ValueError(
                "API_AUTH_ENABLED=true but API_KEYS is empty. "
                "Set API_KEYS (comma-separated), disable auth via "
                "API_AUTH_ENABLED=false, or set DEBUG=true for local dev."
            )
        return self


# Global settings instance
settings = Settings()
