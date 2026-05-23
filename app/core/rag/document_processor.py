"""
LangChain-powered document processing and chunking utilities for RAG pipeline
Supports multiple text splitters for optimal chunking
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal

from langchain_core.documents import Document as LangChainDocument
from langchain_text_splitters import (
    CharacterTextSplitter,
    MarkdownTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


class Document:
    """
    Represents a document chunk with metadata (compatible with LangChain)
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

    @classmethod
    def from_langchain(cls, lc_doc: LangChainDocument) -> "Document":
        """
        Create Document from LangChain Document

        Args:
            lc_doc: LangChain Document instance

        Returns:
            Document instance
        """
        return cls(
            content=lc_doc.page_content,
            metadata=lc_doc.metadata
        )

    def to_langchain(self) -> LangChainDocument:
        """
        Convert to LangChain Document

        Returns:
            LangChain Document instance
        """
        return LangChainDocument(
            page_content=self.content,
            metadata=self.metadata
        )


class DocumentProcessor:
    """
    LangChain-powered document processor for the RAG pipeline.
    Handles intelligent text splitting using multiple strategies.

    Supported splitters:
    - RecursiveCharacterTextSplitter: Best for general text (default)
    - MarkdownTextSplitter: Optimized for Markdown documents
    - CharacterTextSplitter: Simple character-based splitting
    - Code splitters: Language-aware code splitting
    """

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        splitter_type: Literal["recursive", "character", "markdown"] = "recursive"
    ):
        """
        Initialize document processor with LangChain text splitters

        Args:
            chunk_size: Maximum characters per chunk
            chunk_overlap: Number of overlapping characters between chunks
            splitter_type: Type of text splitter to use
        """
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.splitter_type = splitter_type

        # Initialize LangChain text splitter
        self.text_splitter = self._create_text_splitter()

    def _create_text_splitter(self):
        """
        Create LangChain text splitter based on configuration

        Returns:
            LangChain text splitter instance
        """
        if self.splitter_type == "recursive":
            # Best for general text - tries to split on paragraphs, sentences, words
            return RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
                length_function=len,
            )

        elif self.splitter_type == "markdown":
            # Optimized for Markdown documents
            return MarkdownTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )

        elif self.splitter_type == "character":
            # Simple character-based splitting
            return CharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separator="\n\n",
            )

        else:
            raise ValueError(f"Unknown splitter type: {self.splitter_type}")

    def chunk_text(self, text: str, metadata: Dict[str, Any] | None = None) -> List[Document]:
        """
        Split text into overlapping chunks using LangChain text splitters

        Args:
            text: Text to chunk
            metadata: Optional metadata to attach to all chunks

        Returns:
            List of Document objects
        """
        # Use LangChain text splitter
        lc_documents = self.text_splitter.create_documents(
            texts=[text],
            metadatas=[metadata] if metadata else None
        )

        # Convert LangChain Documents to our Document format
        documents = []
        for i, lc_doc in enumerate(lc_documents):
            # Add chunk index to metadata
            chunk_metadata = {
                **lc_doc.metadata,
                "chunk_index": i,
                "total_chunks": len(lc_documents),
            }
            documents.append(Document(
                content=lc_doc.page_content,
                metadata=chunk_metadata
            ))

        return documents

    def load_documents_from_directory(self, directory: str | Path) -> List[Document]:
        """
        Load and process documents from a directory using LangChain loaders
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

        logger.info("Loaded %d document chunks from %s", len(all_documents), directory_path)
        return all_documents

    def _load_file(self, file_path: Path) -> List[Document]:
        """
        Load a single file and chunk it using LangChain loaders

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
            # Read file content
            if file_path.suffix == ".json":
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Handle different JSON structures
                    text = json.dumps(data, indent=2) if isinstance(data, dict) else str(data)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()

            # Use appropriate splitter based on file type
            if file_path.suffix == ".md":
                # Use Markdown splitter for .md files
                markdown_splitter = MarkdownTextSplitter(
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
                lc_documents = markdown_splitter.create_documents(
                    texts=[text],
                    metadatas=[metadata]
                )
            else:
                # Use configured splitter for other files
                lc_documents = self.text_splitter.create_documents(
                    texts=[text],
                    metadatas=[metadata]
                )

            # Convert to our Document format
            documents = []
            for i, lc_doc in enumerate(lc_documents):
                chunk_metadata = {
                    **lc_doc.metadata,
                    "chunk_index": i,
                    "total_chunks": len(lc_documents),
                }
                documents.append(Document(
                    content=lc_doc.page_content,
                    metadata=chunk_metadata
                ))

            return documents

        except Exception as e:
            logger.error("Error loading file %s: %s", file_path, e, exc_info=True)
            return []

    def get_splitter(self):
        """
        Get the underlying LangChain text splitter

        Returns:
            LangChain text splitter instance
        """
        return self.text_splitter
