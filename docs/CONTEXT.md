# AI System Design Copilot — Domain Language

This document defines the ubiquitous language for the AI System Design Copilot project. Use these terms when discussing the codebase, writing documentation, or implementing features.

## Overview

The AI System Design Copilot generates structured system architecture documents from user queries. Users can iteratively refine architectures through multi-turn conversations. The system retrieves relevant design patterns from a vector database (RAG pipeline), uses an LLM to synthesize architectures, and optionally evaluates the quality of generated designs.

## Core Concepts

### Design Generation
Creating a structured system architecture document from a user query. The output is a complete, structured design (not a conversation or interview).

### Refinement
Modifying an existing architecture in-place within the conversation thread. When a user asks to "scale to 100M users" or "add caching," the system updates the current design rather than creating a variant or branch. The LLM returns a complete, updated architecture (not a diff or delta) — each response is self-contained.

### Intent Detection
Classifying whether a user query is requesting a new design (Intent.NEW_DESIGN) or refining the current one (Intent.REFINEMENT). Implemented as a module with a seam, making the logic testable and swappable. Currently uses keyword matching combined with conversation history; could be replaced with ML-based classification without changing callers.

## RAG Pipeline

### Qdrant Vector Database
The system uses Qdrant as its vector database (hardwired - no swappable backends). Stores Reference Patterns as embeddings for semantic search. Can run in-memory (development) or persistent mode (production).

### Reference Patterns
Design patterns and architectural building blocks stored in Qdrant. These are proven strategies (e.g., "consistent hashing for sharding", "Redis caching patterns") that the LLM consults for inspiration when generating architectures. The LLM synthesizes ideas from multiple patterns rather than copy-pasting.

### Context Retrieval
A deep module that retrieves Reference Patterns with quality assurance. Hides all RAG complexity (multi-query expansion, reranking, confidence scoring, hallucination guard) behind a single interface. Callers get "quality-assured reference patterns" in one call, without needing to understand internal RAG mechanics.

### Multi-Query Retrieval
Expanding a user query into multiple sub-queries to improve recall by querying from different technical angles. For example, "Design Instagram" expands to queries about "image storage", "social graph", "feed ranking" to ensure relevant patterns aren't missed due to keyword mismatches. Supports two modes: LLM-based (slow, intelligent) or heuristic-based (fast, rule-driven).

### Reranking
Re-ordering retrieved documents by relevance after initial retrieval. Improves the quality of reference patterns shown to the LLM by prioritizing the most applicable ones.

### Confidence Scoring
Calculating quality indicators for retrieved documents. Measures how well the retrieved reference patterns match the user's query.

### Hallucination Guard
Pre-generation safety check that blocks architecture generation when retrieved reference patterns are insufficient (confidence < 0.3). Prevents the LLM from fabricating architecture advice by enforcing a minimum relevance threshold. When triggered, refuses to generate and returns a structured "insufficient knowledge" response with available topics, similar topics, and actionable guidance. For medium confidence (0.3-0.6), allows generation but includes prominent warnings about limited knowledge.

## Workflow and Session Management

### Design Generation with Session Continuity
Deep module (SystemDesignOrchestrator) that owns the complete flow: session management, workflow execution, and response packaging. Callers provide a query and get back a complete response. All session/state complexity is hidden behind this seam.

### Session
A multi-turn conversation between the user and the system. Persists across API calls via a session ID. Stores conversation history and the current architecture for refinement purposes. Managed entirely by the Orchestrator. Currently uses in-memory storage (development mode) — will be migrated to Redis for production to survive server restarts.

### Workflow State
A request-scoped data structure that flows through the generation pipeline, accumulating information at each step (retrieval → intent detection → generation → evaluation). Created fresh for each API call but hydrated with session data (previous architecture, conversation messages). Internal to the workflow pipeline - not exposed to callers.

## Architecture Output

### Structured Architecture
The generated system design enforces a strict JSON schema with required fields (services, database, scaling_strategy, tradeoffs). This ensures every architecture addresses key aspects and enables validation — the LLM cannot skip important considerations. Also provides machine readability for potential future features like design comparison or metric extraction.

### Architecture Validation
Enforcement of the structured schema during LLM generation. If the LLM fails to produce required fields (e.g., omits `scaling_strategy`), the response is rejected. This prevents incomplete or low-quality designs from being returned to users.

### Design Evaluation
Optional step where the LLM critiques the architecture it just generated, producing a confidence score, strengths/weaknesses, and improvement suggestions. User-facing and educational — helps users understand the quality and limitations of the generated design, teaching them what to look for in a good architecture. Provides transparency about the system's own confidence.

### Knowledge Coverage
The system tracks and exposes what system design topics are available in the knowledge base through dedicated API endpoints (`/knowledge/topics`, `/knowledge/stats`). Provides transparency about coverage, helps users understand what queries will succeed, and enables knowledge gap analysis. The Knowledge Analyzer module extracts topics from documents, categorizes coverage areas, suggests similar topics for failed queries, and provides example queries that would work well.

## LLM Integration

### Tekion Bifrost
Enterprise LLM gateway that provides unified access to multiple LLM providers. The system uses OpenAI SDK configured to route through Bifrost. All LLM calls go through this gateway for monitoring, cost tracking, and compliance.

### LLMClient
Simple interface with two methods: `generate()` for plain text (multi-query retrieval) and `generate_structured()` for JSON output (architecture/evaluation generation). Handles retries, timeouts, and Bifrost authentication. Supports optional Redis caching (1-hour TTL).

## Performance Optimization

### LLM Response Caching
Redis-based caching of LLM responses (1-hour TTL). Cache key includes model, system message, prompt, temperature, and max_tokens. Primarily optimizes cost for duplicate user queries and provides development convenience. Refinements bypass the cache since they include previous architecture in the prompt, making each refinement request unique.

### Embedding Caching
Redis-based caching of embeddings (7-day TTL). More impactful than LLM caching since reference patterns in the vector database don't change frequently. Embeddings for the same text are stable and reusable across many user queries.
