"""
Qdrant vector store implementation using qdrant-client directly
Supports in-memory, persistent local, and server modes.
"""
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.core.rag.document_processor import Document
from app.core.rag.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """
    Qdrant vector store for efficient similarity search using qdrant-client directly.
    Supports in-memory, persistent local, and server modes.
    """

    def __init__(
        self,
        embedding_generator: EmbeddingGenerator | None = None,
        collection_name: str | None = None,
        use_memory: bool | None = None,
        qdrant_url: str | None = None,
    ):
        """
        Initialize Qdrant vector store

        Args:
            embedding_generator: EmbeddingGenerator instance
            collection_name: Name of the Qdrant collection
            use_memory: If True, use in-memory storage. If False, use persistent storage
            qdrant_url: URL of Qdrant server (if using server mode)
        """
        self.embedding_generator = embedding_generator or EmbeddingGenerator()
        self.collection_name = collection_name or settings.qdrant_collection_name
        self.embedding_dimension = self.embedding_generator.dimension

        # Initialize Qdrant client
        use_memory = use_memory if use_memory is not None else settings.qdrant_use_memory

        if use_memory:
            # In-memory mode (for development/testing)
            self.client = QdrantClient(":memory:")
            self.storage_path = None
            self.url = None
            logger.info("Qdrant initialized in-memory mode")
        elif qdrant_url:
            # Server mode (connect to running Qdrant instance)
            self.client = QdrantClient(url=qdrant_url)
            self.storage_path = None
            self.url = qdrant_url
            logger.info("Qdrant connected to server: %s", qdrant_url)
        else:
            # Persistent local storage
            self.storage_path = Path(settings.qdrant_path)
            self.storage_path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(self.storage_path))
            self.url = None
            logger.info("Qdrant initialized with persistent storage: %s", self.storage_path)

        # Track documents with their IDs
        self.document_id_map: Dict[str, Document] = {}

        # Create/connect to collection
        self._initialize_collection()

    def _initialize_collection(self) -> None:
        """
        Initialize or connect to Qdrant collection
        """
        try:
            # Check if collection exists
            collections = self.client.get_collections().collections
            collection_exists = any(c.name == self.collection_name for c in collections)

            if not collection_exists:
                # Create collection with vector configuration
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dimension,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", self.collection_name)
            else:
                logger.info("Connected to existing Qdrant collection: %s", self.collection_name)

        except Exception as e:
            logger.error("Error initializing collection: %s", e, exc_info=True)
            raise

    def add_documents(self, documents: List[Document]) -> None:
        """
        Add documents to the Qdrant collection

        Args:
            documents: List of Document objects to add
        """
        if not documents:
            return

        # Batch-embed all document contents in a single call to avoid N+1
        # round-trips to the embedding provider.
        texts = [doc.content for doc in documents]
        embeddings = self.embedding_generator.generate_embeddings(texts)

        # Prepare points for batch upload
        points = []
        for doc, embedding in zip(documents, embeddings):
            # Generate unique ID for each document
            point_id = str(uuid.uuid4())

            # Prepare payload with document content and metadata
            payload = {
                "content": doc.content,
                "metadata": doc.metadata or {},
            }

            # Create point
            point = PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload=payload,
            )
            points.append(point)

            # Track document by ID
            self.document_id_map[point_id] = doc

        # Batch upsert to Qdrant
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

        logger.info("Added %d documents to Qdrant collection '%s'", len(documents), self.collection_name)

    def search(
        self,
        query: str,
        top_k: int | None = None,
        filter_metadata: Dict[str, Any] | None = None,
    ) -> List[Tuple[Document, float]]:
        """
        Search for similar documents using Qdrant

        Args:
            query: Search query text
            top_k: Number of results to return
            filter_metadata: Optional metadata filters

        Returns:
            List of tuples (Document, similarity_score)
        """
        top_k = top_k or settings.top_k_retrieval

        # Generate embedding for query
        query_embedding = self.embedding_generator.generate_embedding(query)

        # Build filter if metadata is provided
        query_filter = None
        if filter_metadata:
            conditions = []
            for key, value in filter_metadata.items():
                conditions.append(
                    FieldCondition(
                        key=f"metadata.{key}",
                        match=MatchValue(value=value),
                    )
                )
            if conditions:
                query_filter = Filter(must=conditions)

        # Search in Qdrant using query_points
        query_response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding.tolist(),
            limit=top_k,
            query_filter=query_filter,
        )

        # Convert results to Document format
        results = []
        for scored_point in query_response.points:
            # Retrieve document from map or reconstruct from payload
            doc = self.document_id_map.get(scored_point.id)

            if doc is None:
                # Reconstruct document from payload
                payload = scored_point.payload
                doc = Document(
                    content=payload.get("content", ""),
                    metadata=payload.get("metadata", {}),
                )

            # Qdrant with cosine returns similarity score (higher is better)
            results.append((doc, scored_point.score))

        return results

    def delete_collection(self) -> None:
        """
        Delete the entire collection (use with caution!)
        """
        self.client.delete_collection(collection_name=self.collection_name)
        self.document_id_map.clear()
        logger.info("Deleted Qdrant collection: %s", self.collection_name)

    def get_collection_info(self) -> Dict[str, Any]:
        """
        Get information about the collection

        Returns:
            Dictionary with collection stats
        """
        info = self.client.get_collection(collection_name=self.collection_name)
        return {
            "collection_name": self.collection_name,
            "indexed_vectors_count": info.indexed_vectors_count,
            "points_count": info.points_count,
            "segments_count": info.segments_count,
            "status": str(info.status),
        }

    def clear_collection(self) -> None:
        """
        Remove all documents from the collection but keep the collection
        """
        # Delete and recreate collection
        self.client.delete_collection(collection_name=self.collection_name)
        self.document_id_map.clear()
        self._initialize_collection()
        logger.info("Cleared all documents from collection: %s", self.collection_name)
