"""
Test suite for refactored QdrantVectorStore (using qdrant-client directly).

Slice 7 made ``add_documents`` and ``search`` async so the embedding cache
can be awaited. Tests use ``@pytest.mark.asyncio``.
"""
import sys
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.rag.qdrant_store import QdrantVectorStore
from app.core.rag.document_processor import Document


@pytest.mark.asyncio
async def test_basic_operations():
    """Test basic CRUD operations"""
    # Create in-memory store
    store = QdrantVectorStore(use_memory=True)

    # Add documents
    docs = [
        Document(
            content="Design a scalable ride-sharing system like Uber",
            metadata={"topic": "system-design", "difficulty": "hard"}
        ),
        Document(
            content="Implement a URL shortener service",
            metadata={"topic": "system-design", "difficulty": "medium"}
        ),
        Document(
            content="Design a distributed cache system",
            metadata={"topic": "system-design", "difficulty": "hard"}
        ),
    ]

    await store.add_documents(docs)

    # Verify collection info
    info = store.get_collection_info()
    assert info["points_count"] == 3, f"Expected 3 points, got {info['points_count']}"
    assert info["status"] == "green", f"Expected green status, got {info['status']}"


@pytest.mark.asyncio
async def test_search():
    """Test similarity search"""
    store = QdrantVectorStore(use_memory=True)

    docs = [
        Document(content="Machine learning algorithms for classification"),
        Document(content="Deep neural networks and backpropagation"),
        Document(content="Database indexing strategies"),
    ]

    await store.add_documents(docs)

    # Search for ML-related content
    results = await store.search("neural networks and AI", top_k=2)

    assert len(results) <= 2, f"Expected at most 2 results, got {len(results)}"
    assert all(isinstance(r[0], Document) for r in results), "Results should be Document objects"
    assert all(isinstance(r[1], float) for r in results), "Scores should be floats"
    assert results[0][1] >= results[1][1], "Results should be sorted by score"


@pytest.mark.asyncio
async def test_metadata_filtering():
    """Test metadata filtering in search"""
    store = QdrantVectorStore(use_memory=True)

    docs = [
        Document(
            content="Easy coding problem: reverse a string",
            metadata={"difficulty": "easy", "type": "coding"}
        ),
        Document(
            content="Hard system design: design YouTube",
            metadata={"difficulty": "hard", "type": "system-design"}
        ),
        Document(
            content="Medium coding problem: implement LRU cache",
            metadata={"difficulty": "medium", "type": "coding"}
        ),
    ]

    await store.add_documents(docs)

    # Search with filter for "hard" difficulty
    results = await store.search(
        "design problem",
        top_k=10,
        filter_metadata={"difficulty": "hard"}
    )

    assert len(results) == 1, f"Expected 1 hard result, got {len(results)}"
    assert results[0][0].metadata["difficulty"] == "hard"

    # Search with filter for "coding" type
    results = await store.search(
        "problem",
        top_k=10,
        filter_metadata={"type": "coding"}
    )

    assert len(results) == 2, f"Expected 2 coding results, got {len(results)}"
    assert all(r[0].metadata["type"] == "coding" for r in results)


@pytest.mark.asyncio
async def test_collection_management():
    """Test collection clear and delete operations"""
    store = QdrantVectorStore(use_memory=True)

    # Add documents
    docs = [Document(content=f"Document {i}") for i in range(5)]
    await store.add_documents(docs)

    # Verify documents added
    info = store.get_collection_info()
    assert info["points_count"] == 5

    # Clear collection
    store.clear_collection()
    info = store.get_collection_info()
    assert info["points_count"] == 0, "Collection should be empty after clear"
