---
title: AI System Design Copilot
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# AI System Design Copilot

An AI-powered Interactive System Design Interviewer & Assistant that helps engineers learn, practice, and iterate on system design architectures.

## 🎯 Features

- **Intelligent Workflow**: Multi-step design generation with state management
- **Tekion Bifrost Integration**: Enterprise LLM gateway with GPT-4.1-mini support
- **RAG-Enhanced Generation**: Retrieves relevant system design patterns from a curated knowledge base (Qdrant/FAISS)
- **Structured Output**: Enforces strict JSON schemas for consistent, parseable responses
- **Conversational AI**: Maintains context across multiple turns for iterative design refinement
- **Intent Detection**: Automatically detects new designs vs. architecture refinements
- **Evaluation Layer**: AI-powered critique and scoring of generated architectures
- **Token Tracking**: Monitor LLM usage and costs per request
- **Production-Ready**: Built with FastAPI, includes error handling, retries, and async operations
- **⚡ Performance Optimized**: ~15-25 second response time with configurable quality/speed trade-offs

## 🏗️ Architecture

Built using **Tekion Bifrost** LLM gateway with **OpenAI SDK** for production-grade AI workflows:

```
[Client] → [FastAPI] → [Orchestrator] → [Workflow Pipeline]
                                              ↓
                        ┌─────────────────────────────────────────┐
                        │ 1. retrieve_context (RAG/FAISS)        │
                        │ 2. detect_intent (New vs Refinement)    │
                        │ 3. generate_design (Bifrost LLM)        │
                        │ 4. evaluate_design (Optional)           │
                        │ 5. finalize (Package Response)          │
                        └─────────────────────────────────────────┘
                                              ↓
                        [Tekion Bifrost Gateway → GPT-4.1-mini]
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
│   │   ├── llm/              # Bifrost LLM integration
│   │   │   ├── client.py     # OpenAI SDK client for Bifrost
│   │   │   ├── prompts.py    # Prompt templates
│   │   │   └── parser.py     # Structured output parsing
│   │   └── graph/            # Workflow pipeline
│   │       ├── state.py      # State definitions
│   │       └── graph.py      # Workflow logic
│   ├── models/               # Pydantic schemas
│   │   └── schemas.py
│   └── main.py               # FastAPI app entry point
├── scripts/                  # Utility scripts
│   └── initialize_qdrant.py
├── data/                     # Data storage (created on first run)
│   ├── system_design_docs/   # Source documents
│   └── vector_store/         # Qdrant data (if persistent mode)
├── pyproject.toml            # Dependencies
├── .env.example              # Environment template
├── ARCHITECTURE.md           # Detailed architecture docs
└── README.md
```

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.12+
- Tekion LLM Key (get from #ai-platform-support Slack channel)

### 2. Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your Tekion LLM key
TEKION_LLM_KEY=sk-bf-your-key-here
BIFROST_BASE_URL=https://bifrost.stageapp.tekioncloud.xyz/openai
MODEL=gpt-4.1-mini
```

### 4. Initialize Qdrant Vector Database

```bash
# This will create sample documents and build the Qdrant collection
python scripts/initialize_qdrant.py
```

### 5. Run the Server

```bash
# Start the FastAPI server
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive API documentation.

## ⚡ Performance Tuning

The API is optimized for speed by default (~15-25 seconds per request). For quality vs. speed trade-offs, see [PERFORMANCE_OPTIMIZATION.md](./PERFORMANCE_OPTIMIZATION.md).

**Quick Settings:**
```bash
# .env file
ENABLE_MULTI_QUERY_RETRIEVAL=false  # Default: false (faster)
ENABLE_RERANKING=true              # Default: true
REDIS_ENABLED=true                 # Recommended for caching
```

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

### ✅ Phase 2: Complete - **LangChain Integration & Workflow Pipeline**
- ✅ **LangChain LLM Client**: Unified interface for OpenAI/Anthropic
- ✅ **Prompt Templates**: Dynamic, reusable prompt engineering
- ✅ **Structured Output Parser**: JSON schema enforcement
- ✅ **Custom Workflow Pipeline**: Multi-step orchestration with state management
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
