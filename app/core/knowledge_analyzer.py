"""
Knowledge Base Analyzer

Analyzes the vector database to provide information about available topics,
coverage, and document statistics.
"""
import logging
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict

from app.core.config import settings

logger = logging.getLogger(__name__)


class KnowledgeAnalyzer:
    """
    Analyzes knowledge base to provide coverage information.
    
    This helps users understand what topics are available
    and what queries are likely to succeed.
    """
    
    def __init__(self, vector_store=None, data_directory: str = None):
        """
        Initialize knowledge analyzer
        
        Args:
            vector_store: Optional vector store to analyze indexed documents
            data_directory: Directory containing source documents
        """
        self.vector_store = vector_store
        self.data_directory = Path(data_directory or "./data/system_design_docs")
    
    def get_available_topics(self) -> Dict[str, Any]:
        """
        Get list of available system design topics from the knowledge base.
        
        Returns:
            Dictionary with topic information:
            - topics: List of topic names extracted from documents
            - document_count: Total number of documents
            - coverage_areas: Categories of coverage (e.g., "streaming", "ride-sharing")
            - example_queries: Example queries that would work well
        """
        topics = []
        coverage_areas = defaultdict(list)
        
        # Analyze filesystem documents
        if self.data_directory.exists():
            for file_path in self.data_directory.rglob("*"):
                if file_path.is_file() and file_path.suffix in [".md", ".txt", ".json"]:
                    # Extract topic from filename
                    topic_name = file_path.stem.replace("_", " ").title()
                    topic_name = topic_name.replace("System Design", "").strip()
                    
                    if topic_name:
                        topics.append({
                            "name": topic_name,
                            "file": file_path.name,
                            "size_kb": file_path.stat().st_size / 1024,
                        })
                        
                        # Categorize by keywords
                        topic_lower = topic_name.lower()
                        if any(word in topic_lower for word in ["stream", "video", "netflix"]):
                            coverage_areas["streaming"].append(topic_name)
                        elif any(word in topic_lower for word in ["ride", "uber", "location"]):
                            coverage_areas["ride-sharing"].append(topic_name)
                        elif any(word in topic_lower for word in ["social", "feed", "post"]):
                            coverage_areas["social-media"].append(topic_name)
                        elif any(word in topic_lower for word in ["storage", "file", "dropbox"]):
                            coverage_areas["file-storage"].append(topic_name)
                        elif any(word in topic_lower for word in ["message", "chat", "whatsapp"]):
                            coverage_areas["messaging"].append(topic_name)
                        else:
                            coverage_areas["other"].append(topic_name)
        
        # Generate example queries based on available topics
        example_queries = []
        for topic in topics[:5]:  # Top 5 topics
            example_queries.append(f"Design a system like {topic['name']}")
        
        # Get vector store statistics if available
        vector_stats = {}
        if self.vector_store and hasattr(self.vector_store, 'get_collection_info'):
            try:
                vector_stats = self.vector_store.get_collection_info()
            except Exception as e:
                logger.warning(f"Failed to get vector store info: {e}")
        
        return {
            "topics": topics,
            "document_count": len(topics),
            "coverage_areas": dict(coverage_areas),
            "example_queries": example_queries,
            "vector_store_stats": vector_stats,
            "knowledge_base_path": str(self.data_directory),
        }
    
    async def suggest_similar_topics(self, query: str, top_k: int = 3) -> List[str]:
        """
        Suggest available topics similar to the query.

        Async because ``vector_store.search`` is async (it awaits the embedding
        generator + cache).

        Args:
            query: User's query
            top_k: Number of suggestions to return

        Returns:
            List of suggested topic names
        """
        if not self.vector_store:
            return []

        try:
            # Search vector store for similar content
            results = await self.vector_store.search(query, top_k=top_k)
            
            # Extract topic names from metadata
            suggestions = []
            for doc, score in results:
                if doc.metadata and "source" in doc.metadata:
                    source = Path(doc.metadata["source"]).stem
                    topic_name = source.replace("_", " ").title()
                    topic_name = topic_name.replace("System Design", "").strip()
                    if topic_name and topic_name not in suggestions:
                        suggestions.append(topic_name)
            
            return suggestions[:top_k]
        except Exception as e:
            logger.warning(f"Failed to suggest topics: {e}")
            return []
    
    def get_knowledge_stats(self) -> Dict[str, Any]:
        """
        Get detailed statistics about the knowledge base.
        
        Returns:
            Statistics including file counts, sizes, categories
        """
        stats = {
            "total_files": 0,
            "total_size_mb": 0.0,
            "file_types": defaultdict(int),
            "largest_files": [],
        }
        
        if not self.data_directory.exists():
            return stats
        
        files_with_size = []
        for file_path in self.data_directory.rglob("*"):
            if file_path.is_file():
                stats["total_files"] += 1
                size_mb = file_path.stat().st_size / (1024 * 1024)
                stats["total_size_mb"] += size_mb
                stats["file_types"][file_path.suffix] += 1
                
                files_with_size.append({
                    "name": file_path.name,
                    "size_mb": round(size_mb, 3),
                })
        
        # Get top 5 largest files
        stats["largest_files"] = sorted(
            files_with_size,
            key=lambda x: x["size_mb"],
            reverse=True
        )[:5]
        
        stats["total_size_mb"] = round(stats["total_size_mb"], 3)
        stats["file_types"] = dict(stats["file_types"])
        
        return stats
