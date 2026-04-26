"""
Vector store implementation using FAISS for similarity search
"""
from typing import List, Tuple, Dict, Any
from pathlib import Path
import pickle
import numpy as np
import faiss

from app.core.config import settings
from app.core.rag.document_processor import Document
from app.core.rag.embeddings import EmbeddingGenerator


class VectorStore:
    """
    FAISS-based vector store for efficient similarity search.
    Stores document embeddings and retrieves relevant documents based on query similarity.
    """
    
    def __init__(
        self,
        embedding_generator: EmbeddingGenerator | None = None,
        index_path: str | None = None
    ):
        """
        Initialize vector store
        
        Args:
            embedding_generator: EmbeddingGenerator instance
            index_path: Path to save/load FAISS index
        """
        self.embedding_generator = embedding_generator or EmbeddingGenerator()
        self.index_path = Path(index_path or settings.faiss_index_path)
        
        # Initialize FAISS index
        self.dimension = self.embedding_generator.dimension
        self.index: faiss.Index | None = None
        self.documents: List[Document] = []
        
        # Try to load existing index
        if self.index_path.exists():
            self.load()
        else:
            self._initialize_index()
    
    def _initialize_index(self) -> None:
        """Initialize a new FAISS index"""
        # Using IndexFlatL2 for exact search (can be upgraded to IndexIVFFlat for larger datasets)
        self.index = faiss.IndexFlatL2(self.dimension)
        self.documents = []
    
    def add_documents(self, documents: List[Document]) -> None:
        """
        Add documents to the vector store
        
        Args:
            documents: List of Document objects to add
        """
        if not documents:
            return
        
        # Generate embeddings
        texts = [doc.content for doc in documents]
        embeddings = self.embedding_generator.batch_generate_embeddings(texts)
        
        # Convert to numpy array and add to index
        embeddings_array = np.array(embeddings, dtype=np.float32)
        
        if self.index is None:
            self._initialize_index()
        
        self.index.add(embeddings_array)
        self.documents.extend(documents)
        
        print(f"Added {len(documents)} documents to vector store. Total: {len(self.documents)}")
    
    def search(
        self,
        query: str,
        top_k: int | None = None
    ) -> List[Tuple[Document, float]]:
        """
        Search for similar documents based on a query
        
        Args:
            query: Search query text
            top_k: Number of results to return
        
        Returns:
            List of tuples (Document, similarity_score)
        """
        if self.index is None or len(self.documents) == 0:
            return []
        
        top_k = top_k or settings.top_k_retrieval
        
        # Generate query embedding
        query_embedding = self.embedding_generator.generate_embedding(query)
        query_embedding = np.array([query_embedding], dtype=np.float32)
        
        # Search in FAISS index
        distances, indices = self.index.search(query_embedding, min(top_k, len(self.documents)))
        
        # Retrieve documents with scores
        results = []
        for idx, distance in zip(indices[0], distances[0]):
            if idx < len(self.documents):
                # Convert L2 distance to similarity score (lower is better, so invert)
                similarity_score = 1.0 / (1.0 + distance)
                results.append((self.documents[idx], similarity_score))
        
        return results
    
    def save(self, path: str | Path | None = None) -> None:
        """
        Save the FAISS index and documents to disk
        
        Args:
            path: Optional custom path (defaults to configured index_path)
        """
        save_path = Path(path) if path else self.index_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save FAISS index
        faiss.write_index(self.index, str(save_path / "index.faiss"))
        
        # Save documents separately
        with open(save_path / "documents.pkl", 'wb') as f:
            pickle.dump(self.documents, f)
        
        print(f"Vector store saved to {save_path}")
    
    def load(self, path: str | Path | None = None) -> None:
        """
        Load FAISS index and documents from disk
        
        Args:
            path: Optional custom path (defaults to configured index_path)
        """
        load_path = Path(path) if path else self.index_path
        
        index_file = load_path / "index.faiss"
        docs_file = load_path / "documents.pkl"
        
        if not index_file.exists() or not docs_file.exists():
            print(f"No existing index found at {load_path}. Initializing new index.")
            self._initialize_index()
            return
        
        # Load FAISS index
        self.index = faiss.read_index(str(index_file))
        
        # Load documents
        with open(docs_file, 'rb') as f:
            self.documents = pickle.load(f)
        
        print(f"Loaded vector store with {len(self.documents)} documents from {load_path}")
