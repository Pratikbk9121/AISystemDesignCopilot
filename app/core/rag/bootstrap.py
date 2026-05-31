"""
Reusable knowledge-base bootstrap.

Both the FastAPI lifespan (Slice 5) and the `scripts/initialize_qdrant.py` CLI
call into `bootstrap_knowledge()` so there is a single ingestion code path.

Idempotency
-----------
Each chunk gets a deterministic point ID derived from
``uuid5(NAMESPACE_URL, sha256(source_path + "::" + chunk_index))``. Re-running
the bootstrap upserts the same IDs — no duplicate points. When the collection
already holds the expected count and ``force=False``, the seed is skipped.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.rag.document_processor import Document, DocumentProcessor

logger = logging.getLogger(__name__)


def _deterministic_point_id(source_path: str, chunk_index: int) -> str:
    """Return a UUID5 derived from source path + chunk index.

    The combo is hashed with SHA-256 first to give uuid5 a well-distributed
    input that won't collide across long source paths.
    """
    digest = hashlib.sha256(
        f"{source_path}::{chunk_index}".encode("utf-8")
    ).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, digest))


def _chunk_source_path(doc: Document) -> str:
    """Best-effort recovery of the source path from chunk metadata.

    DocumentProcessor stamps ``source_file`` on disk-loaded chunks. For
    sample/in-memory documents that lack a source path, fall back to a
    stable hash of content so deterministic IDs still survive a restart.
    """
    md = doc.metadata or {}
    source = md.get("source_file") or md.get("file_name") or md.get("source")
    if source:
        return str(source)
    return "content:" + hashlib.sha256(doc.content.encode("utf-8")).hexdigest()


def _chunk_index(doc: Document, fallback: int) -> int:
    md = doc.metadata or {}
    idx = md.get("chunk_index")
    if isinstance(idx, int):
        return idx
    return fallback


async def bootstrap_knowledge(
    vector_store: Any,
    data_dir: str | Path | None = None,
    force: bool = False,
) -> dict:
    """Seed ``vector_store`` from ``data_dir`` with idempotent point IDs.

    Async because ``vector_store.add_documents`` is async (it awaits the
    embedding cache + generator).

    Args:
        vector_store: A :class:`QdrantVectorStore` (or anything with
            ``get_collection_info()`` and ``add_documents(documents, ids=...)``).
        data_dir: Directory of .md/.txt/.json knowledge files. Defaults to
            ``settings.knowledge_data_dir``. Created if missing; sample docs
            written if the directory is empty.
        force: When False, the bootstrap exits early if ``points_count`` in the
            collection already equals the chunk count we would produce.

    Returns:
        ``{"status": "skipped"|"loaded", "loaded": N, "skipped": M, "errors": [...]}``.
    """
    data_dir_path = Path(data_dir) if data_dir else Path(settings.knowledge_data_dir)
    errors: list[str] = []

    # Ensure directory exists and has content; seed samples if needed.
    if not data_dir_path.exists():
        logger.info("Knowledge dir missing, creating: %s", data_dir_path)
        data_dir_path.mkdir(parents=True, exist_ok=True)

    if not any(data_dir_path.iterdir()):
        logger.info("Knowledge dir empty, writing sample docs: %s", data_dir_path)
        create_sample_documents(data_dir_path)

    # Load + chunk the corpus.
    processor = DocumentProcessor()
    try:
        documents = processor.load_documents_from_directory(data_dir_path)
    except Exception as e:  # noqa: BLE001
        msg = f"Failed to load documents from {data_dir_path}: {e}"
        logger.error(msg, exc_info=True)
        return {"status": "error", "loaded": 0, "skipped": 0, "errors": [msg]}

    if not documents:
        msg = f"No documents found under {data_dir_path}"
        logger.warning(msg)
        return {"status": "loaded", "loaded": 0, "skipped": 0, "errors": [msg]}

    expected = len(documents)

    # Idempotency fast-path: if the count already matches and caller hasn't
    # forced a re-seed, skip the expensive embedding pass.
    if not force:
        try:
            info = vector_store.get_collection_info()
            points = int(info.get("points_count") or 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read collection points_count: %s", e)
            points = -1
        if points == expected:
            logger.info(
                "knowledge up-to-date, skipping seed (points=%d, expected=%d)",
                points,
                expected,
            )
            return {
                "status": "skipped",
                "loaded": 0,
                "skipped": expected,
                "errors": [],
            }

    # Build deterministic IDs in lockstep with documents.
    ids = [
        _deterministic_point_id(
            _chunk_source_path(doc),
            _chunk_index(doc, fallback=i),
        )
        for i, doc in enumerate(documents)
    ]

    try:
        await vector_store.add_documents(documents, ids=ids)
    except Exception as e:  # noqa: BLE001
        msg = f"vector_store.add_documents failed: {e}"
        logger.error(msg, exc_info=True)
        errors.append(msg)
        return {
            "status": "error",
            "loaded": 0,
            "skipped": 0,
            "errors": errors,
        }

    logger.info(
        "bootstrap_knowledge: loaded %d chunks into collection", expected
    )
    return {"status": "loaded", "loaded": expected, "skipped": 0, "errors": errors}


def create_sample_documents(data_path: str | Path) -> None:
    """Write a couple of sample system-design docs into ``data_path``.

    Called when the knowledge directory is missing or empty so a fresh
    developer environment still has something to retrieve against.
    """
    data_path = Path(data_path)
    data_path.mkdir(parents=True, exist_ok=True)

    sample_docs = {
        "uber_system_design.md": """
# Uber System Design

## Overview
Uber is a ride-sharing platform that connects riders with drivers in real-time.

## Core Components
1. **API Gateway**: Entry point for all client requests
2. **User Service**: Manages user profiles and authentication
3. **Ride Service**: Handles ride requests and state management
4. **Matching Service**: Matches riders with nearby drivers using geospatial indexing
5. **Payment Service**: Processes payments and manages transactions
6. **Notification Service**: Sends real-time updates to users

## Database Architecture
- **PostgreSQL**: Primary database for transactional data (users, rides, payments)
- **Redis**: In-memory cache for session data and real-time locations
- **Cassandra**: Time-series data for ride history and analytics

## Geospatial Indexing
- **QuadTree or S2**: Efficiently find nearby drivers
- **Sharding by geographic region**: Reduces query latency
- **Location updates**: Drivers send location every 4 seconds

## Scaling Strategy
- Horizontal scaling with load balancing
- Database sharding by geographic region
- CDN for static assets
- Message queue (Kafka) for async processing

## Trade-offs
**SQL vs NoSQL**: Hybrid approach - SQL for ACID compliance, NoSQL for scalability
**Consistency vs Availability**: Eventual consistency for ride history, strong consistency for payments
**Push vs Pull**: WebSockets for real-time updates vs HTTP polling
""",
        "netflix_system_design.md": """
# Netflix System Design

## Overview
Netflix is a video streaming platform serving millions of concurrent users globally.

## Core Components
1. **Content Delivery Network (CDN)**: Edge servers for low-latency video delivery
2. **User Service**: Manages profiles, preferences, watch history
3. **Recommendation Engine**: ML-based personalized content recommendations
4. **Video Encoding Service**: Transcodes videos into multiple formats and quality levels
5. **Billing Service**: Manages subscriptions and payments

## Database Architecture
- **Cassandra**: Primary database for distributed, highly available storage
- **MySQL**: User authentication and subscription data
- **ElasticSearch**: Content search and discovery
- **S3**: Video storage before CDN distribution

## Video Delivery
- **Adaptive Bitrate Streaming**: Adjusts quality based on bandwidth
- **Multiple CDN providers**: Amazon CloudFront, Akamai, etc.
- **Open Connect**: Netflix's custom CDN appliances in ISP data centers

## Scaling Strategy
- Microservices architecture with thousands of services
- Multi-region deployment for global reach
- Chaos engineering for resilience testing (Chaos Monkey)
- Auto-scaling based on traffic patterns

## Key Insights
- 90% of traffic served from cache/CDN
- Adaptive bitrate streaming for optimal quality
- Predictive content placement based on viewing patterns
- A/B testing for UI and recommendation improvements
""",
    }

    for filename, content in sample_docs.items():
        file_path = data_path / filename
        file_path.write_text(content, encoding="utf-8")
        logger.info("Wrote sample doc: %s", file_path)


__all__ = ["bootstrap_knowledge", "create_sample_documents"]
