# AI System Design Copilot

An AI-powered Interactive System Design Interviewer & Assistant that helps engineers learn, practice, and iterate on system design architectures.

## 🎯 Features

- **LangGraph State Machine**: Intelligent workflow orchestration for multi-step design generation
- **LangChain Integration**: Unified LLM interface with OpenAI and Anthropic support
- **RAG-Enhanced Generation**: Retrieves relevant system design patterns from a curated knowledge base (FAISS)
- **Structured Output**: Enforces strict JSON schemas for consistent, parseable responses
- **Conversational AI**: Maintains context across multiple turns for iterative design refinement
- **Intent Detection**: Automatically detects new designs vs. architecture refinements
- **Evaluation Layer**: AI-powered critique and scoring of generated architectures
- **Token Tracking**: Monitor LLM usage and costs per request
- **Production-Ready**: Built with FastAPI, includes error handling, retries, and async operations

## 🏗️ Architecture

Built using **LangChain** and **LangGraph** for production-grade AI workflows:

```
[Client] → [FastAPI] → [Orchestrator] → [LangGraph State Machine]
                                              ↓
                        ┌─────────────────────────────────────────┐
                        │ 1. retrieve_context (RAG/FAISS)        │
                        │ 2. detect_intent (New vs Refinement)    │
                        │ 3. generate_design (LangChain LLM)      │
                        │ 4. evaluate_design (Optional)           │
                        │ 5. finalize (Package Response)          │
                        └─────────────────────────────────────────┘
                                              ↓
                        [OpenAI/Anthropic via LangChain]
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed technical documentation.

## 📦 Project Structure

```
AISystemDesignCopilot/
├── app/
│   ├── api/                  # FastAPI routes and endpoints
│   │   └── routes.py
│   ├── core/                 # Business logic
│   │   ├── config.py         # Configuration management
│   │   ├── orchestrator.py   # Main orchestration logic
│   │   ├── state_manager.py  # Conversation state management
│   │   ├── rag/              # RAG pipeline components
│   │   │   ├── document_processor.py
│   │   │   ├── embeddings.py
│   │   │   └── vector_store.py
│   │   ├── llm/              # LangChain integration
│   │   │   ├── client.py     # LLM client wrapper
│   │   │   ├── prompts.py    # Prompt templates
│   │   │   └── parser.py     # Structured output parsing
│   │   └── graph/            # LangGraph workflow
│   │       ├── state.py      # State definitions
│   │       └── graph.py      # Workflow graph
│   ├── models/               # Pydantic schemas
│   │   └── schemas.py
│   └── main.py               # FastAPI app entry point
├── scripts/                  # Utility scripts
│   └── initialize_vector_db.py
├── data/                     # Data storage (created on first run)
│   ├── system_design_docs/   # Source documents
│   └── vector_store/         # FAISS index
├── pyproject.toml            # Dependencies
├── .env.example              # Environment template
├── ARCHITECTURE.md           # Detailed architecture docs
└── README.md
```

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.12+
- OpenAI API key (for embeddings and LLM)

### 2. Installation

```bash
# Install dependencies
pip install -e .

# Or for development
pip install -e ".[dev]"
```

### 3. Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your API keys
OPENAI_API_KEY=your_key_here
```

### 4. Initialize Vector Database

```bash
# This will create sample documents and build the FAISS index
python scripts/initialize_vector_db.py
```

### 5. Run the Server

```bash
# Start the FastAPI server
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive API documentation.

## 📡 API Endpoints

### Generate System Design
```bash
POST /api/v1/system-design/query
```

**Request:**
```json
{
  "query": "Design a ride-sharing system like Uber",
  "session_id": "optional-session-id",
  "include_evaluation": true,
  "context": {
    "scale": "10M daily active users",
    "region": "global"
  }
}
```

**Response:**
```json
{
  "query": "Design a ride-sharing system like Uber",
  "session_id": "abc-123",
  "architecture": {
    "services": ["API Gateway", "User Service", "Ride Service"],
    "database": "PostgreSQL + Redis + Cassandra",
    "scaling_strategy": "Horizontal scaling with sharding",
    "tradeoffs": [...],
    "key_components": {...},
    "api_design": [...]
  },
  "explanation": "Detailed explanation...",
  "evaluation": {
    "confidence_score": 0.85,
    "strengths": [...],
    "weaknesses": [...],
    "suggestions": [...]
  },
  "token_usage": {...}
}
```

### Get Conversation History
```bash
GET /api/v1/system-design/conversation/{session_id}
```

### Health Check
```bash
GET /api/v1/system-design/health
```

## 🔄 Development Status

### ✅ Phase 1: Complete
- ✅ Project scaffolding and dependencies
- ✅ Pydantic models and schemas
- ✅ FastAPI API layer with REST endpoints
- ✅ RAG pipeline (document processing, embeddings, FAISS vector store)
- ✅ Conversation state management
- ✅ Configuration management with environment variables

### ✅ Phase 2: Complete - **LangChain/LangGraph Integration**
- ✅ **LangChain LLM Client**: Unified interface for OpenAI/Anthropic
- ✅ **Prompt Templates**: Dynamic, reusable prompt engineering
- ✅ **Structured Output Parser**: JSON schema enforcement
- ✅ **LangGraph State Machine**: Multi-step workflow orchestration
- ✅ **Intent Detection**: New design vs. refinement detection
- ✅ **Evaluation Chain**: Secondary LLM call for design critique
- ✅ Built-in retry logic and async operations

### 📋 Phase 3: Ready to Test & Extend
- Redis caching layer
- Token usage tracking dashboard
- Advanced refinement ("scale to 10M users", "add feature X")
- Multi-agent collaboration (separate evaluators)
- Production monitoring and observability

## 🧪 Testing

```bash
# Run tests (once implemented)
pytest

# Type checking
mypy app/

# Code formatting
black app/
ruff check app/
```

## 📝 License

MIT License - See LICENSE file for details
