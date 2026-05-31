"""
Demo script showing the complete RAG pipeline in action
Demonstrates all 6 steps: Collection → Chunking → Embeddings → FAISS → Retrieval → Prompt Injection
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.rag import DocumentProcessor, EmbeddingGenerator, VectorStore
from app.core.llm.prompts import PromptTemplates


def demo_rag_pipeline():
    """
    Complete demonstration of the RAG pipeline
    """
    print("=" * 80)
    print("RAG Pipeline Demonstration - System Knowledge-Aware AI")
    print("=" * 80)
    
    # ============================================================================
    # STEP 1: Data Collection
    # ============================================================================
    print("\n📚 STEP 1: DATA COLLECTION")
    print("-" * 80)
    
    sample_knowledge = """
# Twitter System Design

## Overview
Twitter is a microblogging platform handling 400M+ tweets per day.

## Core Services
1. **Tweet Service**: Stores and retrieves tweets
2. **Timeline Service**: Generates user timelines (home, user, search)
3. **Fanout Service**: Distributes tweets to followers
4. **Graph Service**: Manages follower/following relationships
5. **Media Service**: Handles images, videos, GIFs

## Database Architecture
- **MySQL**: User data, tweets, relationships
- **Redis**: Timeline cache, trending topics
- **Cassandra**: Archive of old tweets

## Scaling Strategy
- Write-heavy workload (400M tweets/day)
- Read-heavy timelines (600k requests/sec)
- Hybrid fanout: Push for most users, pull for celebrities
- Content Delivery Network for media

## Key Trade-offs
**Push vs Pull Fanout**:
- Push: Pre-compute timelines, fast reads, high write amplification
- Pull: Compute on-demand, slow reads, efficient writes
- Hybrid: Push for regular users (< 1M followers), pull for celebrities
"""
    
    print(f"Sample Document Length: {len(sample_knowledge)} characters")
    print("\nContent Preview:")
    print(sample_knowledge[:200] + "...")
    
    # ============================================================================
    # STEP 2: Chunking
    # ============================================================================
    print("\n\n✂️  STEP 2: CHUNKING (300-1000 tokens with overlap)")
    print("-" * 80)
    
    doc_processor = DocumentProcessor(chunk_size=500, chunk_overlap=100)
    chunks = doc_processor.chunk_text(
        sample_knowledge,
        metadata={"source": "twitter_design.md", "topic": "social_media"}
    )
    
    print(f"Generated {len(chunks)} chunks")
    for i, chunk in enumerate(chunks, 1):
        print(f"\nChunk {i} ({len(chunk.content)} chars):")
        print(f"  {chunk.content[:150]}...")
        print(f"  Metadata: {chunk.metadata}")
    
    # ============================================================================
    # STEP 3: Generate Embeddings
    # ============================================================================
    print("\n\n🧮 STEP 3: GENERATE EMBEDDINGS (text-embedding-3-small)")
    print("-" * 80)
    
    embedding_gen = EmbeddingGenerator()
    print(f"Model: {embedding_gen.model}")
    print(f"Embedding Dimension: {embedding_gen.dimension}")
    
    texts = [chunk.content for chunk in chunks]
    embeddings = embedding_gen.generate_embeddings(texts)
    
    print(f"\nGenerated {len(embeddings)} embeddings")
    print(f"First embedding shape: {embeddings[0].shape}")
    print(f"First 5 values: {embeddings[0][:5]}")
    
    # ============================================================================
    # STEP 4: Store in FAISS
    # ============================================================================
    print("\n\n💾 STEP 4: STORE IN FAISS (IndexFlatL2)")
    print("-" * 80)
    
    vector_store = VectorStore(embedding_generator=embedding_gen)
    vector_store.add_documents(chunks)
    
    print(f"FAISS Index Type: {type(vector_store.index).__name__}")
    print(f"Total Documents: {len(vector_store.documents)}")
    print(f"Index Dimension: {vector_store.dimension}")
    print(f"Storage Path: {vector_store.index_path}")
    
    # ============================================================================
    # STEP 5: Retrieval (Top-K Search)
    # ============================================================================
    print("\n\n🔍 STEP 5: RETRIEVAL (Top-K Similarity Search)")
    print("-" * 80)
    
    test_queries = [
        "How does Twitter handle timeline generation?",
        "What database does Twitter use?",
        "Explain Twitter's fanout strategy"
    ]
    
    for query in test_queries:
        print(f"\n📝 Query: '{query}'")
        results = vector_store.search(query, top_k=2)
        
        print(f"   Found {len(results)} relevant chunks:")
        for i, (doc, score) in enumerate(results, 1):
            print(f"\n   Result {i} (Similarity: {score:.4f}):")
            print(f"   {doc.content[:200]}...")
    
    # ============================================================================
    # STEP 6: Context Injection into Prompt
    # ============================================================================
    print("\n\n💉 STEP 6: CONTEXT INJECTION INTO PROMPT")
    print("-" * 80)
    
    user_query = "Design a microblogging platform similar to Twitter"
    results = vector_store.search(user_query, top_k=3)
    
    # Extract retrieved documents
    retrieved_docs = [doc.content for doc, score in results]
    retrieved_context = "\n\n".join(retrieved_docs)
    
    # Format the complete prompt
    prompts = PromptTemplates()
    user_prompt = prompts.format_system_design_user_prompt(
        query=user_query,
        retrieved_context=retrieved_context,
        chat_history="",
        additional_context=""
    )
    
    print(f"\n📄 User Query: '{user_query}'")
    print(f"\n🎯 Retrieved {len(retrieved_docs)} relevant documents")
    print(f"\n📝 Final Prompt Length: {len(user_prompt)} characters")
    print("\n--- Generated Prompt Preview ---")
    print(user_prompt[:500] + "...")
    print("\n--- End Preview ---")
    
    # ============================================================================
    # SUMMARY
    # ============================================================================
    print("\n\n" + "=" * 80)
    print("✅ RAG PIPELINE COMPLETE!")
    print("=" * 80)
    print("""
The system is now KNOWLEDGE-AWARE:

✓ Documents collected and processed
✓ Text chunked into overlapping segments  
✓ Embeddings generated using OpenAI models
✓ Vectors stored in FAISS for efficient search
✓ Relevant context retrieved via similarity search
✓ Context injected into LLM prompts

💡 OUTCOME:
Your AI copilot now generates responses based on real system design knowledge
rather than just generic LLM knowledge. It references actual architectures
(Twitter, Uber, Netflix) from your knowledge base!

🚀 NEXT STEPS:
1. Add more documents to ./data/system_design_docs/
2. Run: python scripts/initialize_vector_db.py
3. Query the system and see knowledge-aware responses!
""")


if __name__ == "__main__":
    try:
        demo_rag_pipeline()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\n💡 Make sure you have:")
        print("1. Set TEKION_LLM_KEY in your .env file")
        print("2. Installed all dependencies: pip install -r requirements.txt")
        import traceback
        traceback.print_exc()
