"""
FastAPI application entry point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api.routes import router as system_design_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown events
    """
    # Startup
    print(f"Starting {settings.app_name} v{settings.app_version}")
    print(f"LLM Provider: {settings.llm_provider}")
    print(f"Vector DB: {settings.vector_db_type}")
    print(f"Redis Enabled: {settings.redis_enabled}")
    
    # Initialize components here (vector store, cache, etc.)
    # TODO: Initialize vector store on startup
    # TODO: Initialize Redis connection if enabled
    
    yield
    
    # Shutdown
    print("Shutting down gracefully...")
    # Cleanup resources
    # TODO: Close Redis connection
    # TODO: Save any pending state


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

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
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
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error": str(exc) if settings.debug else "An unexpected error occurred"
        }
    )
