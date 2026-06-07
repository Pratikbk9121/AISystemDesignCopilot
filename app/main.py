"""
FastAPI application entry point
"""
import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.cache import get_redis_client, CacheManager
from app.core.dependencies import get_vector_store as _get_vector_store_dep
from app.core.dependencies import set_cache_managers, set_vector_store
from app.api.routes import router as system_design_router
from app.middleware import (
    ErrorLoggingMiddleware,
    MetricsMiddleware,
    RateLimitExceeded,
    RequestIdMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    limiter,
    rate_limit_exceeded_handler,
    require_api_key,
)

# Setup logging first
setup_logging()
logger = logging.getLogger(__name__)

# Sentry must be initialized BEFORE FastAPI() so the FastApiIntegration
# auto-instruments the app at construction time. Off by default — only wires
# up when SENTRY_DSN is set.
if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.app_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,
    )
    logger.info(
        "Sentry initialized: env=%s traces=%.2f",
        settings.sentry_environment,
        settings.sentry_traces_sample_rate,
    )

# Global cache instances (will be set in lifespan)
redis_client = None
vector_store = None


async def _probe_bifrost() -> str:
    """Phase-B helper: probe the active LLM endpoint with a 3s timeout.

    Probes whichever upstream the active provider points at (Bifrost or an
    openai-compatible gateway like Gemini) by hitting
    ``settings.effective_llm_base_url``. 2xx and 4xx both count as "up" — the
    host answered. Timeout or 5xx is "down". Any local exception is treated as
    "down" so prod boot can decide whether to fail. Kept out of the lifespan
    body to keep phases readable.
    """
    import httpx  # local import: only paid when probe is enabled

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.effective_llm_base_url)
        if 200 <= resp.status_code < 500:
            return "up"
        return "down"
    except Exception as e:  # noqa: BLE001 — probe must never crash startup itself
        logger.warning("Bifrost probe failed: %s", e)
        return "down"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ordered startup phases:
        A. Config sanity      — defensive guard on TEKION_LLM_KEY
        B. Bifrost probe      — optional; in prod, "down" raises
        C. Redis init         — soft dep; must run BEFORE Qdrant so the
                                vector store can be built with a
                                CachedEmbeddingGenerator
        D. Qdrant init + seed — optional bootstrap when collection is empty
        E. Summary log        — single STARTUP_SUMMARY line for ops/dashboards
    Shutdown closes Qdrant (releases file lock) then Redis.
    """
    global redis_client, vector_store

    # --- Phase A: Config sanity --------------------------------------------
    # The Settings model_validator already enforces the provider-required env
    # vars, but we re-assert the effective key here so a future config refactor
    # can't silently regress the fail-fast contract for either provider.
    assert settings.effective_llm_api_key, (
        "LLM API key must be set — provide TEKION_LLM_KEY (provider=bifrost) "
        "or LLM_API_KEY (provider=openai_compatible)"
    )
    llm_status = "ok"

    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("Environment: %s", settings.environment)
    logger.info("LLM provider: %s", settings.llm_provider)
    logger.info("LLM base URL: %s", settings.effective_llm_base_url)
    logger.info("Model: %s", settings.effective_llm_model)
    logger.info(
        "Vector DB: Qdrant (Collection: %s)", settings.qdrant_collection_name
    )

    # --- Phase B: Bifrost probe --------------------------------------------
    bifrost_status = "skipped"
    if settings.bifrost_healthcheck_on_startup:
        bifrost_status = await _probe_bifrost()
        if bifrost_status == "down" and settings.environment == "prod":
            raise RuntimeError(
                "LLM healthcheck reported 'down' in prod "
                f"(provider={settings.llm_provider}, "
                f"base_url={settings.effective_llm_base_url})"
            )
        logger.info("Bifrost probe: %s", bifrost_status)

    # --- Phase C: Redis init ----------------------------------------------
    # Runs BEFORE Qdrant so the embedding cache exists when the vector
    # store is constructed — otherwise QdrantVectorStore's default
    # EmbeddingGenerator() bypasses Redis for the lifetime of the process.
    redis_status = "disabled"
    embedding_cache = None
    if settings.redis_enabled:
        try:
            redis_client = get_redis_client()
            if await redis_client.is_available():
                embedding_cache = CacheManager(redis_client, namespace="emb:")
                llm_cache = CacheManager(redis_client, namespace="llm:")
                conversation_cache = CacheManager(redis_client, namespace="conv:")
                set_cache_managers(
                    embedding_cache=embedding_cache,
                    llm_cache=llm_cache,
                    conversation_cache=conversation_cache,
                )
                redis_status = "ok"
                logger.info(
                    "Redis cache initialized (emb_ttl=%ds llm_ttl=%ds conv_ttl=%ds)",
                    settings.cache_embedding_ttl,
                    settings.cache_llm_ttl,
                    settings.cache_conversation_ttl,
                )
            else:
                redis_status = "unavailable"
                logger.warning(
                    "Redis unreachable — running without cache. "
                    "Expect higher LLM latency and embedding-provider cost."
                )
        except Exception as e:
            redis_status = "error"
            logger.error(
                "Redis init failed; continuing without cache "
                "(higher latency + LLM/embedding cost): %s",
                e,
                exc_info=True,
            )
    else:
        logger.warning(
            "REDIS_ENABLED=false — caching disabled. "
            "Expect higher LLM latency and embedding-provider cost."
        )

    # --- Phase D: Qdrant init + optional auto-seed -------------------------
    qdrant_status = "down"
    points_count = 0
    try:
        from app.core.rag import QdrantVectorStore
        from app.core.rag.bootstrap import bootstrap_knowledge
        from app.core.rag.embeddings import (
            CachedEmbeddingGenerator,
            EmbeddingGenerator,
        )

        # Inject a CachedEmbeddingGenerator when Redis is up so query- and
        # passage-side embeddings hit the `emb:` namespace. Falls back to the
        # uncached generator when Redis is disabled/unreachable.
        embedding_generator = (
            CachedEmbeddingGenerator(cache_manager=embedding_cache)
            if embedding_cache is not None
            else EmbeddingGenerator()
        )
        vector_store = QdrantVectorStore(embedding_generator=embedding_generator)
        set_vector_store(vector_store)

        info = vector_store.get_collection_info()
        points_count = int(info.get("points_count") or 0)
        logger.info(
            "Qdrant collection=%s points=%d",
            info.get("collection_name"),
            points_count,
        )

        if points_count == 0 and settings.auto_seed_knowledge:
            logger.info(
                "Qdrant empty + AUTO_SEED_KNOWLEDGE=true → seeding from %s",
                settings.knowledge_data_dir,
            )
            seed_result = await bootstrap_knowledge(
                vector_store, data_dir=settings.knowledge_data_dir
            )
            logger.info("bootstrap_knowledge result: %s", seed_result)
            # Refresh count so STARTUP_SUMMARY reflects post-seed state.
            try:
                points_count = int(
                    vector_store.get_collection_info().get("points_count") or 0
                )
            except Exception:  # noqa: BLE001
                pass

        # Structured post-seed boot log. Emitted AFTER any auto-seed pass so
        # the points count reflects the live state we'll actually serve from.
        # Wave 2D: makes a regression (e.g. baked image shipping an empty
        # collection) loud at boot — no need to wait for the first query to
        # see "zero retrieval hits".
        try:
            info = vector_store.get_collection_info()
            logger.info(
                "qdrant.boot collection=%s points=%d hybrid=%s",
                info.get("collection_name"),
                int(info.get("points_count") or 0),
                info.get("hybrid"),
            )
        except Exception as e:  # noqa: BLE001 — diagnostic only.
            logger.warning("qdrant.boot log failed: %s", e)

        qdrant_status = f"ok(points={points_count})"
    except Exception as e:
        if settings.qdrant_required_on_startup:
            logger.error(
                "Qdrant init failed and QDRANT_REQUIRED_ON_STARTUP=true: %s",
                e,
                exc_info=True,
            )
            raise
        logger.error(
            "Qdrant init failed; continuing in degraded mode "
            "(QDRANT_REQUIRED_ON_STARTUP=false): %s",
            e,
            exc_info=True,
        )
        qdrant_status = "degraded"

    # --- Phase E: Summary --------------------------------------------------
    logger.info(
        "STARTUP_SUMMARY llm=%s qdrant=%s redis=%s bifrost=%s",
        llm_status,
        qdrant_status,
        redis_status,
        bifrost_status,
    )

    yield

    # --- Shutdown ----------------------------------------------------------
    logger.info("Shutting down gracefully")

    if vector_store is not None:
        try:
            vector_store.close()
        except Exception as e:  # noqa: BLE001
            logger.error("Error closing Qdrant vector store: %s", e, exc_info=True)

    if redis_client:
        try:
            await redis_client.close()
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error("Error closing Redis: %s", e, exc_info=True)

    logger.info("Shutdown complete")


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

# --- Middleware stack -------------------------------------------------------
# Starlette runs middleware in REVERSE registration order — i.e. the LAST
# add_middleware() call is the OUTERMOST wrapper that sees the raw request
# first and the final response last. We want this order at request time
# (outermost → innermost):
#
#     RequestIdMiddleware            (set request_id_var, stamp response header)
#       → SlowAPIMiddleware          (rate limit by caller_id / IP)
#         → CORSMiddleware           (preflight + cross-origin headers)
#           → SecurityHeadersMiddleware  (CSP, X-Frame-Options, etc.)
#             → ErrorLoggingMiddleware
#               → RequestLoggingMiddleware
#                 → MetricsMiddleware (innermost — measures route handler only)
#
# So we register them inner-first below.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Innermost: HTTP metrics. Timing here excludes upstream middleware overhead.
app.add_middleware(MetricsMiddleware)

# Logging next so request/error logs benefit from the request_id ContextVar
# set by the outermost RequestIdMiddleware.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ErrorLoggingMiddleware)

# Security headers wrap the CORS response so the headers also land on
# CORS-handled preflight (204) replies.
app.add_middleware(SecurityHeadersMiddleware)

# CORS middleware configuration. Explicit allowlists (no wildcards) so
# `allow_credentials=True` is safe — browsers reject `*` + credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "x-api-key", "x-request-id"],
    expose_headers=["x-request-id"],
    max_age=600,
)

# SlowAPI sits outside CORS so a 429 reply still carries CORS headers and the
# browser surfaces the rate-limit error to the user code.
app.add_middleware(SlowAPIMiddleware)

# Outermost: correlation ID. Must run before everything else so every log line
# emitted inside a request — including SlowAPI's 429 path — picks up the ID.
app.add_middleware(RequestIdMiddleware)

# Include routers. Auth is applied at the router level so every endpoint under
# /api/v1/system-design requires `x-api-key`; the top-level `/` and `/health`
# routes below are intentionally unauthenticated (liveness probes, root info).
app.include_router(
    system_design_router,
    prefix=settings.api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint
    """
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    """
    Unauthenticated liveness probe. No I/O — just confirms the process is up
    and answering. Use `/readyz` for dependency-aware readiness.
    """
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


# --- /readyz -----------------------------------------------------------------
# Per-probe wall-clock cap. Keeps `/readyz` from blocking a k8s readiness probe
# even when a dep is gone — better to return 503 fast than to time the probe
# itself out and have k8s nuke the pod.
_PROBE_TIMEOUT_S = 0.5
# Total cap for the whole endpoint. ~3 probes * 500ms each = 1500ms worst case.
_READYZ_TOTAL_TIMEOUT_S = 1.5


async def _probe_redis() -> dict[str, object]:
    """Ping Redis via the existing global client; report status + latency."""
    import time

    if not settings.redis_enabled:
        return {"status": "skipped", "latency_ms": 0}
    client = get_redis_client()
    start = time.perf_counter()
    try:
        # is_available() is now natively async (redis.asyncio); just await it
        # with the per-probe timeout.
        ok = await asyncio.wait_for(
            client.is_available(),
            timeout=_PROBE_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        return {"status": "down", "latency_ms": int((time.perf_counter() - start) * 1000)}
    latency = int((time.perf_counter() - start) * 1000)
    return {"status": "up" if ok else "down", "latency_ms": latency}


async def _probe_qdrant() -> dict[str, object]:
    """List collections on the global vector store; reuse the singleton."""
    import time

    vs = _get_vector_store_dep()
    if vs is None:
        # Lifespan didn't init Qdrant (degraded boot). Not ready.
        return {"status": "down", "latency_ms": 0}
    start = time.perf_counter()
    try:
        await asyncio.wait_for(
            anyio.to_thread.run_sync(vs.client.get_collections),
            timeout=_PROBE_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        return {"status": "down", "latency_ms": int((time.perf_counter() - start) * 1000)}
    return {"status": "up", "latency_ms": int((time.perf_counter() - start) * 1000)}


async def _probe_bifrost_readyz() -> dict[str, object]:
    """Optional Bifrost probe; controlled by READYZ_CHECK_BIFROST."""
    import time

    if not settings.readyz_check_bifrost:
        return {"status": "skipped", "latency_ms": 0}

    import httpx

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            resp = await client.get(settings.effective_llm_base_url)
        latency = int((time.perf_counter() - start) * 1000)
        # 2xx/4xx → host answered → up. 5xx → down.
        up = 200 <= resp.status_code < 500
        return {"status": "up" if up else "down", "latency_ms": latency}
    except Exception:  # noqa: BLE001
        return {"status": "down", "latency_ms": int((time.perf_counter() - start) * 1000)}


@app.get("/readyz", tags=["Health"])
async def readyz() -> JSONResponse:
    """
    Dependency-aware readiness probe.

    Required deps: Qdrant always required (the app can't serve queries without
    it). Redis required only when REDIS_ENABLED=true. Bifrost required only
    when READYZ_REQUIRE_BIFROST=true.

    Returns 200 when all required deps respond. 503 otherwise. The body always
    lists every probed dep so an operator can see which one is failing.
    """
    try:
        redis_check, qdrant_check, bifrost_check = await asyncio.wait_for(
            asyncio.gather(
                _probe_redis(),
                _probe_qdrant(),
                _probe_bifrost_readyz(),
            ),
            timeout=_READYZ_TOTAL_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        # Hit the total-budget cap. Treat as not-ready but answer fast.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "checks": {"_overall": {"status": "down", "reason": "timeout"}},
            },
        )

    checks = {
        "redis": redis_check,
        "qdrant": qdrant_check,
        "bifrost": bifrost_check,
    }

    not_ready = False
    # Qdrant is always required.
    if qdrant_check["status"] == "down":
        not_ready = True
    # Redis required only if enabled.
    if settings.redis_enabled and redis_check["status"] == "down":
        not_ready = True
    # Bifrost required only if explicitly opted in.
    if settings.readyz_require_bifrost and bifrost_check["status"] == "down":
        not_ready = True

    status_code = (
        status.HTTP_503_SERVICE_UNAVAILABLE if not_ready else status.HTTP_200_OK
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "not_ready" if not_ready else "ready",
            "checks": checks,
        },
    )


# --- /metrics ----------------------------------------------------------------
# Optional basic auth for the scrape endpoint. Both user + password must be set
# to enable; otherwise the endpoint is open (typical when scraped from a
# private cluster network).
_metrics_basic = HTTPBasic(auto_error=False)


def _metrics_auth_dep(
    credentials: HTTPBasicCredentials | None = Depends(_metrics_basic),
) -> None:
    """Constant-time basic-auth check when METRICS_BASIC_AUTH_* configured."""
    expected_user = settings.metrics_basic_auth_user
    expected_pw = settings.metrics_basic_auth_password
    if not expected_user or not expected_pw:
        return  # auth disabled
    if credentials is None or not (
        hmac.compare_digest(credentials.username, expected_user)
        and hmac.compare_digest(credentials.password, expected_pw)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


if settings.metrics_enabled:
    # Imported lazily so the module load doesn't pay for prometheus_client
    # when METRICS_ENABLED=false.
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    @app.get("/metrics", tags=["Observability"])
    async def metrics(_: None = Depends(_metrics_auth_dep)) -> Response:
        """Prometheus text exposition. Returns the current registry snapshot."""
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )


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
