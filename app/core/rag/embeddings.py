"""
Embedding generation for RAG pipeline
"""
from typing import List
import numpy as np
from openai import OpenAI

from app.core.config import settings


class EmbeddingGenerator:
    """
    Generates embeddings for text using OpenAI's embedding models.
    Supports batching for efficient processing.
    """
    
    def __init__(self, model: str | None = None):
        """
        Initialize embedding generator
        
        Args:
            model: Embedding model name (defaults to config setting)
        """
        self.model = model or settings.embedding_model
        
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured")
        
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.dimension = self._get_embedding_dimension()
    
    def _get_embedding_dimension(self) -> int:
        """
        Get the dimension of embeddings for the current model
        
        Returns:
            Embedding dimension size
        """
        # Known dimensions for OpenAI embedding models
        dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return dimensions.get(self.model, 1536)
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding for a single text
        
        Args:
            text: Text to embed
        
        Returns:
            Numpy array of embedding vector
        """
        embeddings = self.generate_embeddings([text])
        return embeddings[0]
    
    def generate_embeddings(self, texts: List[str]) -> List[np.ndarray]:
        """
        Generate embeddings for multiple texts (batched)
        
        Args:
            texts: List of texts to embed
        
        Returns:
            List of numpy arrays containing embedding vectors
        """
        if not texts:
            return []
        
        # Clean texts
        cleaned_texts = [text.replace("\n", " ").strip() for text in texts]
        
        try:
            # Call OpenAI API
            response = self.client.embeddings.create(
                model=self.model,
                input=cleaned_texts
            )
            
            # Extract embeddings and convert to numpy arrays
            embeddings = [
                np.array(item.embedding, dtype=np.float32)
                for item in response.data
            ]
            
            return embeddings
        
        except Exception as e:
            raise RuntimeError(f"Failed to generate embeddings: {str(e)}") from e
    
    def batch_generate_embeddings(
        self,
        texts: List[str],
        batch_size: int = 100
    ) -> List[np.ndarray]:
        """
        Generate embeddings in batches for large datasets
        
        Args:
            texts: List of texts to embed
            batch_size: Number of texts per batch
        
        Returns:
            List of numpy arrays containing embedding vectors
        """
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings = self.generate_embeddings(batch)
            all_embeddings.extend(embeddings)
            
            # Optional: Add progress logging
            if (i + batch_size) % 500 == 0:
                print(f"Processed {min(i + batch_size, len(texts))}/{len(texts)} embeddings")
        
        return all_embeddings
