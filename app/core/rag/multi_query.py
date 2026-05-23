"""
Multi-Query Retrieval for improved RAG context coverage
Breaks down complex queries into sub-queries to retrieve more comprehensive context
"""
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Tuple

from app.core.llm.client import LLMClient
from app.core.rag.document_processor import Document

logger = logging.getLogger(__name__)


class MultiQueryRetriever:
    """
    Generates multiple sub-queries from a user query and retrieves documents for each.
    This improves context coverage by capturing different aspects of the query.

    Supports two modes:
    1. LLM-based: Uses LLM to generate sub-queries (slow but intelligent)
    2. Heuristic-based: Uses rule-based expansion (fast but deterministic)
    """

    def __init__(self, llm_client: LLMClient | None = None, use_llm: bool = False):
        """
        Initialize multi-query retriever

        Args:
            llm_client: LLM client for query generation (creates new if None)
            use_llm: Whether to use LLM for query generation (default: False, uses heuristics)
        """
        self.llm_client = llm_client or LLMClient()
        self.use_llm = use_llm

        # System design domain keywords for heuristic expansion
        self.technical_aspects = [
            "scalability", "database", "API", "caching", "load balancing",
            "microservices", "consistency", "availability", "architecture",
            "data model", "storage", "messaging", "authentication"
        ]

    def _generate_sub_queries_heuristic(self, query: str, num_queries: int = 3) -> List[str]:
        """
        Generate sub-queries using fast heuristic-based approach (NO LLM call)

        This method:
        1. Extracts key system names from the query
        2. Applies domain-specific templates for system design
        3. Generates focused queries for different technical aspects

        Args:
            query: Original user query
            num_queries: Number of sub-queries to generate

        Returns:
            List of sub-queries including the original
        """
        sub_queries = []
        query_lower = query.lower()

        # Extract system name/type (e.g., "URL shortener", "Twitter", "Instagram")
        system_match = re.search(r'(?:design|build|create)\s+(?:a\s+)?(?:scalable\s+)?(.+?)(?:\s+like|\s+system|\s+that|\s+for|$)', query, re.IGNORECASE)
        system_name = system_match.group(1).strip() if system_match else "system"

        # Template 1: High-level architecture focus
        sub_queries.append(f"{system_name} architecture components and services")

        # Template 2: Database/storage focus
        if any(word in query_lower for word in ["store", "data", "save", "persist"]):
            sub_queries.append(f"{system_name} database design and data storage")
        else:
            sub_queries.append(f"{system_name} scalability patterns")

        # Template 3: Scale/performance focus
        if any(word in query_lower for word in ["scale", "million", "billion", "users", "traffic"]):
            sub_queries.append(f"{system_name} high-scale performance optimization")
        else:
            sub_queries.append(f"{system_name} API design and interfaces")

        # Template 4: Specific feature focus (if mentioned)
        features = []
        if "real-time" in query_lower or "realtime" in query_lower:
            features.append("real-time")
        if "search" in query_lower:
            features.append("search")
        if "notification" in query_lower or "push" in query_lower:
            features.append("notification")
        if "message" in query_lower or "chat" in query_lower:
            features.append("messaging")

        if features:
            sub_queries.append(f"{system_name} {' '.join(features)} implementation")

        # Always include original query first
        all_queries = [query] + sub_queries

        # Return up to num_queries + 1 (original + N sub-queries)
        result = all_queries[:num_queries + 1]

        logger.debug("Heuristic query expansion: %s -> %d queries", query[:50], len(result))

        return result

    async def generate_sub_queries(self, query: str, num_queries: int = 3) -> List[str]:
        """
        Generate sub-queries from the original query

        Supports two modes:
        - Heuristic mode (default, use_llm=False): Fast rule-based expansion (~0.1s)
        - LLM mode (use_llm=True): Intelligent but slow LLM-based expansion (~2-4s)

        Args:
            query: Original user query
            num_queries: Number of sub-queries to generate

        Returns:
            List of sub-queries including the original
        """
        # Use fast heuristic mode by default (no LLM call!)
        if not self.use_llm:
            logger.info("Using FAST heuristic query expansion (no LLM call)")
            return self._generate_sub_queries_heuristic(query, num_queries)

        # LLM-based generation (slower but more intelligent)
        logger.info("Using LLM-based query expansion (adds 2-4s latency)")
        system_message = """You are an expert at breaking down complex system design questions into simpler sub-questions.
Your task is to generate alternative phrasings and focused sub-questions that will help retrieve comprehensive documentation.

Generate questions that:
1. Rephrase the original query in different ways
2. Focus on specific technical aspects (scalability, database, APIs, etc.)
3. Target different levels of abstraction (high-level architecture vs implementation details)

Return ONLY a JSON array of strings, no explanation."""

        user_prompt = f"""Original Query: "{query}"

Generate {num_queries} sub-queries or alternative phrasings that would help retrieve comprehensive documentation for this system design question.

OUTPUT FORMAT (JSON array):
["sub-query 1", "sub-query 2", "sub-query 3"]"""

        try:
            response = await self.llm_client.generate_structured(
                prompt=user_prompt,
                system_message=system_message
            )
            
            # Handle both list and dict responses
            if isinstance(response, list):
                sub_queries = response
            elif isinstance(response, dict) and "queries" in response:
                sub_queries = response["queries"]
            elif isinstance(response, dict) and "sub_queries" in response:
                sub_queries = response["sub_queries"]
            else:
                # Fallback: try to extract any list from the response
                for value in response.values():
                    if isinstance(value, list):
                        sub_queries = value
                        break
                else:
                    sub_queries = []
            
            # Always include original query
            all_queries = [query] + sub_queries[:num_queries]
            return all_queries[:num_queries + 1]

        except Exception as e:
            logger.warning("Failed to generate sub-queries: %s", e, exc_info=True)
            # Fallback: return just the original query
            return [query]
    
    async def retrieve_with_multi_query(
        self,
        query: str,
        vector_store,
        num_sub_queries: int = 3,
        top_k_per_query: int = 3
    ) -> List[Tuple[Document, float]]:
        """
        Retrieve documents using multi-query approach with concurrent searches
        dispatched via a threadpool.

        ``vector_store.search`` is a synchronous (blocking) call, so we offload
        each sub-query search to a thread via ``asyncio.to_thread`` and gather
        the results. This gives real I/O concurrency for network-bound Qdrant
        calls (the GIL is released during socket I/O), but it is NOT true async
        parallelism — there is no native async vector store interface here.

        Args:
            query: Original user query
            vector_store: Vector store instance to search
            num_sub_queries: Number of sub-queries to generate
            top_k_per_query: Documents to retrieve per sub-query

        Returns:
            De-duplicated list of (Document, score) tuples sorted by relevance
        """
        # Track total time for performance monitoring
        total_start = time.time()

        # Generate sub-queries
        query_gen_start = time.time()
        queries = await self.generate_sub_queries(query, num_sub_queries)
        query_gen_time = time.time() - query_gen_start

        logger.info("Multi-Query Retrieval - Generated %d queries in %.2fs:",
                    len(queries), query_gen_time)
        for i, q in enumerate(queries):
            logger.debug("  %d. %s", i+1, q)

        # Concurrent vector searches via threadpool (vector_store.search is sync)
        search_start = time.time()

        async def search_async(sub_query: str) -> List[Tuple[Document, float]]:
            """
            Run the synchronous ``vector_store.search`` in the default
            threadpool so multiple searches can overlap on I/O. This is
            threadpool-based concurrency, not native async parallelism.
            """
            # vector_store.search is synchronous; offload to a threadpool so
            # gather() can overlap multiple blocking calls on network I/O.
            return await asyncio.to_thread(vector_store.search, sub_query, top_k_per_query)

        # Dispatch all searches concurrently via threadpool
        logger.debug("Dispatching %d concurrent vector searches via threadpool...", len(queries))
        all_search_results = await asyncio.gather(*[search_async(q) for q in queries])

        search_time = time.time() - search_start
        estimated_sequential_time = len(queries) * 0.5  # Rough estimate: 0.5s per search
        logger.info(
            "Concurrent search via threadpool completed in %.2fs "
            "(estimated sequential: ~%.2fs, speedup: %.1fx)",
            search_time, estimated_sequential_time,
            estimated_sequential_time / max(search_time, 0.01)
        )

        # De-duplicate by content, keeping highest score
        all_results: Dict[str, Tuple[Document, float]] = {}

        for results in all_search_results:
            for doc, score in results:
                content_hash = hash(doc.content)
                if content_hash not in all_results or score > all_results[content_hash][1]:
                    all_results[content_hash] = (doc, score)

        # Sort by score (highest first)
        sorted_results = sorted(all_results.values(), key=lambda x: x[1], reverse=True)

        total_time = time.time() - total_start
        logger.info("✅ Retrieved %d unique documents in %.2fs total (query gen: %.2fs, search: %.2fs)",
                    len(sorted_results), total_time, query_gen_time, search_time)

        return sorted_results
