"""
Document processing and chunking utilities for RAG pipeline
"""
from typing import List, Dict, Any
from pathlib import Path
import json

from app.core.config import settings


class Document:
    """
    Represents a document chunk with metadata
    """
    def __init__(
        self,
        content: str,
        metadata: Dict[str, Any] | None = None,
        doc_id: str | None = None
    ):
        self.content = content
        self.metadata = metadata or {}
        self.doc_id = doc_id or self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate a unique document ID"""
        import hashlib
        return hashlib.md5(self.content.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            "doc_id": self.doc_id,
            "content": self.content,
            "metadata": self.metadata
        }


class DocumentProcessor:
    """
    Processes documents for the RAG pipeline.
    Handles chunking, cleaning, and preparation for embedding.
    """
    
    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None
    ):
        """
        Initialize document processor
        
        Args:
            chunk_size: Maximum characters per chunk
            chunk_overlap: Number of overlapping characters between chunks
        """
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
    
    def chunk_text(self, text: str, metadata: Dict[str, Any] | None = None) -> List[Document]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: Text to chunk
            metadata: Optional metadata to attach to all chunks
        
        Returns:
            List of Document objects
        """
        if len(text) <= self.chunk_size:
            return [Document(content=text, metadata=metadata)]
        
        chunks = []
        start = 0
        
        while start < len(text):
            # Find the end of the chunk
            end = start + self.chunk_size
            
            # If not at the end, try to break at a sentence boundary
            if end < len(text):
                # Look for sentence endings (., !, ?, \n)
                for separator in ['. ', '! ', '? ', '\n\n', '\n']:
                    last_sep = text[start:end].rfind(separator)
                    if last_sep != -1:
                        end = start + last_sep + len(separator)
                        break
            
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunk_metadata = {
                    **(metadata or {}),
                    "chunk_start": start,
                    "chunk_end": end,
                }
                chunks.append(Document(content=chunk_text, metadata=chunk_metadata))
            
            # Move start position with overlap
            start = end - self.chunk_overlap
        
        return chunks
    
    def load_documents_from_directory(self, directory: str | Path) -> List[Document]:
        """
        Load and process documents from a directory.
        Supports .txt, .md, .json files.
        
        Args:
            directory: Path to directory containing documents
        
        Returns:
            List of processed Document objects
        """
        directory_path = Path(directory)
        if not directory_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        all_documents = []
        
        # Process all supported files
        for file_path in directory_path.rglob("*"):
            if file_path.is_file() and file_path.suffix in [".txt", ".md", ".json"]:
                documents = self._load_file(file_path)
                all_documents.extend(documents)
        
        return all_documents
    
    def _load_file(self, file_path: Path) -> List[Document]:
        """
        Load a single file and chunk it
        
        Args:
            file_path: Path to the file
        
        Returns:
            List of Document chunks
        """
        metadata = {
            "source_file": str(file_path),
            "file_name": file_path.name,
            "file_type": file_path.suffix,
        }
        
        try:
            if file_path.suffix == ".json":
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Handle different JSON structures
                    text = json.dumps(data, indent=2) if isinstance(data, dict) else str(data)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
            
            return self.chunk_text(text, metadata)
        
        except Exception as e:
            print(f"Error loading file {file_path}: {e}")
            return []
