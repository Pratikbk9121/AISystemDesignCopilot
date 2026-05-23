"""
FastAPI application entry point
"""
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.cache import get_redis_client, CacheManager
from app.core.dependencies import set_cache_managers, set_vector_store
from app.api.routes import router as system_design_router
from app.middleware import RequestLoggingMiddleware, ErrorLoggingMiddleware

# Setup logging first
setup_logging()
logger = logging.getLogger(__name__)

# Global cache instances (will be set in lifespan)
redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown events
    """
    global redis_client

    # Startup
    logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"📡 Bifrost Base URL: {settings.bifrost_base_url}")
    logger.info(f"🤖 Model: {settings.model}")
    logger.info(f"🗂️  Vector DB: Qdrant (Collection: {settings.qdrant_collection_name})")
    logger.info(f"🔧 Redis Enabled: {settings.redis_enabled}")
    logger.info(f"📊 Logging Level: {settings.log_level}")

    # Initialize Qdrant vector store (once at startup for performance)
    try:
        logger.info("🔄 Initializing Qdrant vector store...")
        from app.core.rag import QdrantVectorStore

        vector_store = QdrantVectorStore()
        set_vector_store(vector_store)
        logger.info("✅ Qdrant vector store initialized")

        # Log collection info
        info = vector_store.get_collection_info()
        logger.info(f"   - Collection: {info.get('collection_name')}")
        logger.info(f"   - Points: {info.get('points_count', 0)}")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Qdrant vector store: {e}", exc_info=True)

    # Initialize Redis client
    if settings.redis_enabled:
        try:
            redis_client = get_redis_client()

            if redis_client.is_available():
                # Initialize cache managers with different namespaces
                embedding_cache = CacheManager(redis_client, namespace="emb:")
                llm_cache = CacheManager(redis_client, namespace="llm:")
                conversation_cache = CacheManager(redis_client, namespace="conv:")

                # Set global cache managers
                set_cache_managers(
                    embedding_cache=embedding_cache,
                    llm_cache=llm_cache,
                    conversation_cache=conversation_cache
                )

                logger.info("✅ Redis cache initialized successfully")
                logger.info(f"   - Embedding cache TTL: {settings.cache_embedding_ttl}s")
                logger.info(f"   - LLM cache TTL: {settings.cache_llm_ttl}s")
                logger.info(f"   - Conversation cache TTL: {settings.cache_conversation_ttl}s")
            else:
                logger.warning("⚠️  Redis not available, caching disabled")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Redis: {e}", exc_info=True)

    yield

    # Shutdown
    logger.info("🛑 Shutting down gracefully...")

    # Close Redis connection
    if redis_client:
        try:
            redis_client.close()
            logger.info("✅ Redis connection closed")
        except Exception as e:
            logger.error(f"❌ Error closing Redis: {e}", exc_info=True)

    logger.info("👋 Shutdown complete")


# Initialize FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered Interactive System Design Interviewer & Assistant",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add logging middleware
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ErrorLoggingMiddleware)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(system_design_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint
    """
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/system-design/health"
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Global exception handler for unhandled errors
    """
    logger.error(
        f"Unhandled exception: {type(exc).__name__}",
        exc_info=True,
        extra={
            "extra_data": {
                "path": str(request.url),
                "method": request.method,
                "error_type": type(exc).__name__,
            }
        }
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error": str(exc) if settings.debug else "An unexpected error occurred"
        }
    )
