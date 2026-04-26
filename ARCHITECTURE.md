# Architecture Documentation

## System Overview

The AI System Design Copilot is built using **LangChain** and **LangGraph** for intelligent orchestration of the system design generation workflow.

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
│  - Invokes LangGraph workflow                        │
└──────────────────┬───────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────┐
│          LangGraph State Machine                     │
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

### 2. **LangGraph State Machine**

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

**Workflow Nodes**:
1. **retrieve_context**: RAG retrieval from vector DB
2. **detect_intent**: Determine if new design or refinement
3. **generate_design**: LLM generation with structured output
4. **evaluate_design**: Optional quality assessment
5. **finalize**: Package response

**Conditional Edges**:
- Evaluation is only triggered if `include_evaluation=True`

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

### Why LangGraph?
✅ **State Management**: Built-in state tracking across nodes
✅ **Conditional Flows**: Easy evaluation bypass
✅ **Debugging**: Clear visualization of workflow steps
✅ **Scalability**: Can add more nodes (caching, validation, etc.)

### Why LangChain?
✅ **Provider Abstraction**: Easy to switch between OpenAI/Anthropic
✅ **Prompt Templates**: Reusable, testable prompt engineering
✅ **Structured Outputs**: Native support for JSON schema enforcement
✅ **Built-in Retries**: Resilience to API failures

### Structured Output Strategy
- Use LLM's native structured output when available (OpenAI with function calling)
- Fallback to JSON parsing with format instructions
- Pydantic validation ensures type safety

## Data Flow Example

1. **User Request**: "Design Uber"
2. **API Layer**: Validates request, creates/loads session
3. **Orchestrator**: Invokes LangGraph workflow
4. **LangGraph**:
   - Retrieves 5 relevant docs about ride-sharing systems
   - Detects this is a new design (not refinement)
   - Constructs prompt with RAG context + conversation history
   - Calls OpenAI GPT-4 with structured output schema
   - Parses JSON response into `SystemArchitecture`
   - Optionally evaluates design with second LLM call
   - Packages final response
5. **API Layer**: Returns structured JSON to client
6. **State Manager**: Saves conversation + architecture for future refinement

## Extension Points

### Adding New Nodes
```python
workflow.add_node("validate_design", self._validate_design)
workflow.add_edge("generate_design", "validate_design")
```

### Adding Caching
- Redis integration in LangGraph nodes
- Cache key: hash(query + context)

### Adding Multi-Agent Collaboration
- Separate LangGraph workflows for different expertise
- Architecture review agent
- Cost optimization agent
- Security review agent

## Performance Considerations

- **Embeddings**: Batched generation (100 docs at a time)
- **LLM Calls**: Async/await for concurrency
- **Vector Search**: FAISS IndexFlatL2 (exact search, scales to 100k docs)
- **Future**: Switch to IndexIVFFlat for > 1M documents
