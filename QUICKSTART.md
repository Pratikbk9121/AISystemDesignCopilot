# Quick Start Guide

Get the AI System Design Copilot running in 5 minutes!

## Prerequisites

- Python 3.12+
- OpenAI API key (required for embeddings and LLM)
- Anthropic API key (optional, for Claude models)

## Setup Steps

### 1. Clone and Install

```bash
# Navigate to project directory
cd AISystemDesignCopilot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your favorite editor
nano .env  # or vim, code, etc.
```

Add your API keys:
```env
OPENAI_API_KEY=sk-your-key-here
LLM_PROVIDER=openai
```

### 3. Initialize Vector Database

```bash
# This creates sample system design documents and builds FAISS index
python scripts/initialize_vector_db.py
```

Expected output:
```
============================================================
Initializing Vector Database
============================================================

1. Initializing components...
2. Loading documents from ./data/system_design_docs...
   Loaded 6 document chunks
3. Generating embeddings and building vector index...
   Added 6 documents to vector store. Total: 6
4. Saving vector store to ./data/vector_store/faiss_index...
   Vector store saved to data/vector_store/faiss_index
5. Testing retrieval with sample query...

✅ Vector database initialized successfully!
```

### 4. Start the Server

```bash
# Start FastAPI server
uvicorn app.main:app --reload --port 8000
```

Or use the convenience script:
```bash
./run.sh
```

You should see:
```
🚀 Starting AI System Design Copilot...
✅ Starting FastAPI server on http://localhost:8000
📖 API Documentation: http://localhost:8000/docs
```

## Test the API

### Option 1: Interactive Swagger UI

Open http://localhost:8000/docs in your browser and use the interactive API documentation.

### Option 2: cURL

```bash
curl -X POST "http://localhost:8000/api/v1/system-design/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Design a ride-sharing system like Uber",
    "include_evaluation": true
  }'
```

### Option 3: Python

```python
import requests
import json

url = "http://localhost:8000/api/v1/system-design/query"

# First query
response = requests.post(url, json={
    "query": "Design a scalable URL shortener like bit.ly",
    "include_evaluation": True,
    "context": {
        "scale": "1 billion URLs, 100M daily clicks"
    }
})

result = response.json()
print(json.dumps(result, indent=2))

# Save session ID for follow-up
session_id = result["session_id"]

# Follow-up refinement query
refinement = requests.post(url, json={
    "query": "How would you modify this to handle 10x more traffic?",
    "session_id": session_id,
    "include_evaluation": True
})

print(json.dumps(refinement.json(), indent=2))
```

## Understanding the Response

The API returns a structured JSON response:

```json
{
  "query": "Design a ride-sharing system like Uber",
  "session_id": "abc-123-...",
  "architecture": {
    "services": ["API Gateway", "User Service", "Ride Service", ...],
    "database": "PostgreSQL + Redis + Cassandra",
    "scaling_strategy": "Horizontal scaling with sharding",
    "tradeoffs": [
      {
        "aspect": "Database Choice",
        "options": ["SQL", "NoSQL", "Hybrid"],
        "recommendation": "Hybrid approach...",
        "considerations": [...]
      }
    ],
    "key_components": {...},
    "api_design": [...],
    "non_functional_requirements": {...}
  },
  "explanation": "Detailed explanation...",
  "evaluation": {
    "confidence_score": 0.85,
    "strengths": [...],
    "weaknesses": [...],
    "suggestions": [...]
  },
  "token_usage": {
    "prompt_tokens": 1200,
    "completion_tokens": 800,
    "total_tokens": 2000,
    "estimated_cost_usd": 0.024
  },
  "retrieved_context": ["doc1...", "doc2..."]
}
```

## Troubleshooting

### "OpenAI API key not configured"
- Ensure `.env` file exists in project root
- Verify `OPENAI_API_KEY` is set correctly
- Restart the server after changing `.env`

### "No documents found in vector store"
- Run `python scripts/initialize_vector_db.py`
- Check that `data/system_design_docs/` contains .md files
- Verify FAISS index created in `data/vector_store/faiss_index/`

### Import errors
- Make sure you installed with `pip install -e .`
- Verify Python version: `python --version` (need 3.12+)
- Check virtual environment is activated

## Next Steps

- 📖 Read [ARCHITECTURE.md](./ARCHITECTURE.md) for technical deep dive
- 🧪 Explore the LangGraph workflow visualization at `/docs`
- 🔧 Add your own system design documents to `data/system_design_docs/`
- 🚀 Extend the LangGraph workflow with custom nodes

## Example Queries to Try

1. **E-commerce Platform**
   ```
   "Design Amazon.com with product catalog, shopping cart, and checkout"
   ```

2. **Social Network**
   ```
   "Design Twitter with real-time feeds, follow/unfollow, and trending topics"
   ```

3. **Video Streaming**
   ```
   "Design Netflix with 4K streaming for 100M concurrent users"
   ```

4. **Refinement Follow-up**
   ```
   First: "Design Instagram"
   Then: "How would you add Stories feature to this design?"
   ```

Happy designing! 🎨🏗️
