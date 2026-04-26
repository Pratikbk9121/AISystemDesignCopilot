"""
Script to initialize the vector database with system design documentation
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.rag import DocumentProcessor, EmbeddingGenerator, VectorStore
from app.core.config import settings


def initialize_vector_store(data_directory: str = "./data/system_design_docs"):
    """
    Initialize the vector store with documents from a directory
    
    Args:
        data_directory: Path to directory containing system design documentation
    """
    print("=" * 60)
    print("Initializing Vector Database")
    print("=" * 60)
    
    # Initialize components
    print("\n1. Initializing components...")
    doc_processor = DocumentProcessor()
    embedding_generator = EmbeddingGenerator()
    vector_store = VectorStore(embedding_generator=embedding_generator)
    
    # Check if data directory exists
    data_path = Path(data_directory)
    if not data_path.exists():
        print(f"\n⚠️  Data directory not found: {data_directory}")
        print("Creating directory and sample documents...")
        data_path.mkdir(parents=True, exist_ok=True)
        create_sample_documents(data_path)
    
    # Load and process documents
    print(f"\n2. Loading documents from {data_directory}...")
    documents = doc_processor.load_documents_from_directory(data_directory)
    print(f"   Loaded {len(documents)} document chunks")
    
    if len(documents) == 0:
        print("\n⚠️  No documents found. Please add .txt, .md, or .json files to the data directory.")
        return
    
    # Add documents to vector store
    print("\n3. Generating embeddings and building vector index...")
    vector_store.add_documents(documents)
    
    # Save the index
    print(f"\n4. Saving vector store to {settings.faiss_index_path}...")
    vector_store.save()
    
    # Test retrieval
    print("\n5. Testing retrieval with sample query...")
    test_query = "How to design a scalable ride-sharing system?"
    results = vector_store.search(test_query, top_k=3)
    
    print(f"\n   Query: '{test_query}'")
    print(f"   Found {len(results)} results:")
    for i, (doc, score) in enumerate(results, 1):
        print(f"\n   Result {i} (score: {score:.4f}):")
        print(f"   {doc.content[:200]}...")
        if doc.metadata:
            print(f"   Metadata: {doc.metadata}")
    
    print("\n" + "=" * 60)
    print("✅ Vector database initialized successfully!")
    print("=" * 60)


def create_sample_documents(data_path: Path):
    """
    Create sample system design documents for testing
    
    Args:
        data_path: Path to save sample documents
    """
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

## Scaling Strategy
- Horizontal scaling with load balancing
- Database sharding by geographic region
- CDN for static assets
- Message queue (Kafka) for async processing

## Trade-offs
**SQL vs NoSQL**: Hybrid approach - SQL for ACID compliance, NoSQL for scalability
**Consistency vs Availability**: Eventual consistency for ride history, strong consistency for payments
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

## Scaling Strategy
- Microservices architecture with thousands of services
- Multi-region deployment for global reach
- Chaos engineering for resilience testing
- Auto-scaling based on traffic patterns

## Key Insights
- 90% of traffic served from cache/CDN
- Adaptive bitrate streaming for optimal quality
- Predictive content placement based on viewing patterns
        """,
    }
    
    for filename, content in sample_docs.items():
        file_path = data_path / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"   Created: {file_path}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialize vector database with system design docs")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="./data/system_design_docs",
        help="Directory containing system design documentation"
    )
    
    args = parser.parse_args()
    initialize_vector_store(args.data_dir)
