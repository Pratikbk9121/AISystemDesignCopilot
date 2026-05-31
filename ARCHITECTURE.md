# Architecture Documentation

## System Overview

The AI System Design Copilot is built using **LangChain** components with a **custom workflow pipeline** for intelligent orchestration of the system design generation workflow.

## High-Level Architecture

```
┌─────────────┐
│   Client    │
│ (UI/Postman)│
└──────┬──────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│           FastAPI Application Layer                  │
│  - REST endpoints                                    │
│  - Request validation (Pydantic)                     │
│  - Session management                                │
└──────────────────┬───────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────┐
│         System Design Orchestrator                   │
│  - Coordinates the entire workflow                   │
│  - Manages conversation history                      │
│  - Invokes workflow pipeline                         │
└──────────────────┬───────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────┐
│          Custom Workflow Pipeline                    │
│          (SystemDesignGraph)                         │
│                                                       │
│  ┌─────────────────────────────────────────┐        │
│  │  1. retrieve_context                     │        │
│  │     - Query vector database (FAISS)      │        │
│  │     - Fetch top-k relevant docs          │        │
│  └────────────────┬─────────────────────────┘        │
│                   ▼                                   │
│  ┌─────────────────────────────────────────┐        │
│  │  2. detect_intent                        │        │
│  │     - New design vs refinement           │        │
│  │     - Check conversation history         │        │
│  └────────────────┬─────────────────────────┘        │
│                   ▼                                   │
│  ┌─────────────────────────────────────────┐        │
│  │  3. generate_design                      │        │
│  │     - Build dynamic prompt               │        │
│  │     - LLM call (via LangChain)           │        │
│  │     - Parse structured output            │        │
│  └────────────────┬─────────────────────────┘        │
│                   ▼                                   │
│            ┌─────────────┐                           │
│            │ Evaluate?   │                           │
│            └───┬─────┬───┘                           │
│                │     │                                │
│       Yes ◄────┘     └────► No                       │
│        │                    │                         │
│        ▼                    │                         │
│  ┌─────────────┐           │                         │
│  │ 4. evaluate │           │                         │
│  │   _design   │           │                         │
│  └─────┬───────┘           │                         │
│        │                   │                         │
│        └─────────┬─────────┘                         │
│                  ▼                                    │
│         ┌────────────────┐                           │
│         │  5. finalize   │                           │
│         │   - Package    │                           │
│         │   - Return     │                           │
│         └────────────────┘                           │
└──────────────────────────────────────────────────────┘
                   │
    ┌──────────────┴──────────────┐
    ▼                             ▼
┌─────────────┐          ┌──────────────────┐
│ LLM Engine  │          │   Vector Store   │
│ (LangChain) │          │     (FAISS)      │
│  - OpenAI   │          │  - Embeddings    │
│  - Anthropic│          │  - Documents     │
└─────────────┘          └──────────────────┘
```

## Component Details

### 1. **LangChain Integration**

#### LLMClient (`app/core/llm/client.py`)
- Unified interface to OpenAI and Anthropic
- Handles both text and structured JSON outputs
- Built-in retry logic and timeout handling
- Token usage tracking
- Cost estimation

#### PromptTemplates (`app/core/llm/prompts.py`)
- **System Design Prompt**: Main template for generating architectures
- **Evaluation Prompt**: Template for critiquing designs
- **Refinement Prompt**: Template for modifying existing architectures
- Dynamic variable injection (RAG context, chat history, user constraints)

#### StructuredOutputParser (`app/core/llm/parser.py`)
- Enforces Pydantic schema validation
- Handles JSON extraction from markdown
- Provides format instructions for prompts

### 2. **Custom Workflow Pipeline**

#### SystemDesignGraph (`app/core/graph/graph.py`)

**State Definition** (`SystemDesignState`):
```python
{
    "query": str,
    "session_id": str,
    "messages": List[Dict],  # Accumulated conversation
    "retrieved_documents": List[str],
    "architecture_json": Dict | None,
    "explanation": str | None,
    "evaluation_json": Dict | None,
    "previous_architecture": Dict | None,
    "is_refinement": bool,
    ...
}
```

**Workflow Steps**:
1. **retrieve_context**: RAG retrieval from vector DB using multi-query, reranking, and confidence scoring
2. **detect_intent**: Determine if new design or refinement
3. **generate_design**: LLM generation with structured output
4. **evaluate_design**: Optional quality assessment
5. **finalize**: Package response

**Conditional Logic**:
- Evaluation is only executed if `include_evaluation=True`
- Hallucination guard may short-circuit the workflow if insufficient context detected

### 3. **RAG Pipeline**

#### Document Processing
- **Chunking**: Intelligent text splitting with overlap
- **Embedding**: OpenAI embeddings (text-embedding-3-small)
- **Storage**: FAISS for efficient similarity search

#### Vector Store
- FAISS IndexFlatL2 for exact nearest neighbor search
- Persistent storage (save/load capability)
- Top-k retrieval based on cosine similarity

### 4. **Conversation State Management**

- In-memory storage (development)
- Tracks conversation history per session
- Stores last generated architecture for refinement queries
- Thread-safe operations

## Key Design Decisions

### Why Custom Workflow Pipeline?
✅ **Simplicity**: Lightweight async functions without framework overhead
✅ **Full Control**: Direct control over state management and flow
✅ **Flexibility**: Easy to add custom logic and conditional execution
✅ **Transparency**: Clear execution path without abstraction layers
✅ **Advanced RAG**: Integrated multi-query, reranking, confidence scoring, and hallucination guard

### Why LangChain?
✅ **Provider Abstraction**: Easy to switch between OpenAI/Anthropic
✅ **Embeddings Integration**: Seamless support for HuggingFace and OpenAI embeddings
✅ **Vector Store Utilities**: Built-in support for FAISS and Qdrant
✅ **Prompt Templates**: Reusable, testable prompt engineering
✅ **Mature Ecosystem**: Well-tested components with active community

### Structured Output Strategy
- Use LLM's native structured output when available (OpenAI with function calling)
- Fallback to JSON parsing with format instructions
- Pydantic validation ensures type safety

## Data Flow Example

1. **User Request**: "Design Uber"
2. **API Layer**: Validates request, creates/loads session
3. **Orchestrator**: Invokes custom workflow pipeline
4. **Workflow Pipeline**:
   - Multi-query retrieval: Generates 3 sub-queries for better context coverage
   - Re-ranks retrieved documents by relevance
   - Calculates confidence score (checks if sufficient context exists)
   - Hallucination guard: Verifies context adequacy before generation
   - Detects this is a new design (not refinement)
   - Constructs prompt with RAG context + conversation history
   - Calls LLM (via Tekion Bifrost) with structured output instructions
   - Parses JSON response into `SystemArchitecture`
   - Optionally evaluates design with second LLM call
   - Packages final response with confidence metrics
5. **API Layer**: Returns structured JSON to client
6. **State Manager**: Saves conversation + architecture for future refinement (Redis or in-memory)

## Extension Points

### Adding New Pipeline Steps
```python
# In SystemDesignGraph class
async def _validate_design(self, state: SystemDesignState) -> Dict[str, Any]:
    # Custom validation logic
    return {"validation_passed": True, "current_step": "validate_design"}

# In run() method, add step:
state = await self._validate_design(state)
```

### Adding Caching
- Redis caching already integrated for embeddings, LLM responses, and conversations
- LLM responses cached by prompt hash
- Embeddings cached by text hash
- Cache key: hash(content + provider + model)

### Adding Multi-Agent Collaboration
- Create separate SystemDesignGraph instances for different expertise
- Architecture review pipeline
- Cost optimization pipeline
- Security review pipeline
- Aggregate results from multiple pipelines

## Performance Considerations

- **Embeddings**: Batched generation (100 docs at a time)
- **LLM Calls**: Async/await for concurrency
- **Vector Search**: FAISS IndexFlatL2 (exact search, scales to 100k docs)
- **Future**: Switch to IndexIVFFlat for > 1M documents
