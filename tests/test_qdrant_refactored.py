"""
Test suite for refactored QdrantVectorStore (using qdrant-client directly)
This validates that the refactored implementation works correctly without langchain-qdrant
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.rag.qdrant_store import QdrantVectorStore
from app.core.rag.document_processor import Document
from app.core.rag.embeddings import EmbeddingGenerator


def test_basic_operations():
    """Test basic CRUD operations"""
    print("Testing basic operations...")
    
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
    
    store.add_documents(docs)
    
    # Verify collection info
    info = store.get_collection_info()
    assert info["points_count"] == 3, f"Expected 3 points, got {info['points_count']}"
    assert info["status"] == "green", f"Expected green status, got {info['status']}"
    
    print("  ✅ Basic operations passed")


def test_search():
    """Test similarity search"""
    print("Testing similarity search...")
    
    store = QdrantVectorStore(use_memory=True)
    
    docs = [
        Document(content="Machine learning algorithms for classification"),
        Document(content="Deep neural networks and backpropagation"),
        Document(content="Database indexing strategies"),
    ]
    
    store.add_documents(docs)
    
    # Search for ML-related content
    results = store.search("neural networks and AI", top_k=2)
    
    assert len(results) <= 2, f"Expected at most 2 results, got {len(results)}"
    assert all(isinstance(r[0], Document) for r in results), "Results should be Document objects"
    assert all(isinstance(r[1], float) for r in results), "Scores should be floats"
    assert results[0][1] >= results[1][1], "Results should be sorted by score"
    
    print(f"  Found {len(results)} results")
    print(f"  Top result score: {results[0][1]:.4f}")
    print("  ✅ Search passed")


def test_metadata_filtering():
    """Test metadata filtering in search"""
    print("Testing metadata filtering...")
    
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
    
    store.add_documents(docs)
    
    # Search with filter for "hard" difficulty
    results = store.search(
        "design problem",
        top_k=10,
        filter_metadata={"difficulty": "hard"}
    )
    
    assert len(results) == 1, f"Expected 1 hard result, got {len(results)}"
    assert results[0][0].metadata["difficulty"] == "hard"
    
    # Search with filter for "coding" type
    results = store.search(
        "problem",
        top_k=10,
        filter_metadata={"type": "coding"}
    )
    
    assert len(results) == 2, f"Expected 2 coding results, got {len(results)}"
    assert all(r[0].metadata["type"] == "coding" for r in results)
    
    print("  ✅ Metadata filtering passed")


def test_collection_management():
    """Test collection clear and delete operations"""
    print("Testing collection management...")
    
    store = QdrantVectorStore(use_memory=True)
    
    # Add documents
    docs = [Document(content=f"Document {i}") for i in range(5)]
    store.add_documents(docs)
    
    # Verify documents added
    info = store.get_collection_info()
    assert info["points_count"] == 5
    
    # Clear collection
    store.clear_collection()
    info = store.get_collection_info()
    assert info["points_count"] == 0, "Collection should be empty after clear"
    
    print("  ✅ Collection management passed")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("QdrantVectorStore Refactored Tests")
    print("(Using qdrant-client directly, without langchain-qdrant)")
    print("=" * 60)
    print()
    
    try:
        test_basic_operations()
        test_search()
        test_metadata_filtering()
        test_collection_management()
        
        print()
        print("=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return True
        
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"❌ Test failed: {e}")
        print("=" * 60)
        return False
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ Unexpected error: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
