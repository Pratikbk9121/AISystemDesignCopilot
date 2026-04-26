# Testing Guide

## Quick Start Testing

### 1. Start the Server

```bash
# Option 1: Using the run script
./run.sh

# Option 2: Direct uvicorn
uvicorn app.main:app --reload --port 8000
```

### 2. Verify Health

```bash
curl http://localhost:8000/api/v1/system-design/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "AI System Design Copilot",
  "version": "0.1.0"
}
```

## Testing API Endpoints

### Generate System Design

**cURL Example:**
```bash
curl -X POST "http://localhost:8000/api/v1/system-design/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Design a ride-sharing system like Uber for 10 million daily active users",
    "include_evaluation": true,
    "context": {
      "scale": "10M DAU",
      "region": "North America"
    }
  }'
```

**Python Example:**
```python
import requests

url = "http://localhost:8000/api/v1/system-design/query"
payload = {
    "query": "Design a scalable URL shortener like bit.ly",
    "include_evaluation": True,
    "context": {
        "requirements": "100M URLs, 1B redirects per month"
    }
}

response = requests.post(url, json=payload)
result = response.json()

print(f"Services: {result['architecture']['services']}")
print(f"Database: {result['architecture']['database']}")
print(f"Confidence: {result['evaluation']['confidence_score']}")
```

### Conversational Follow-up

```bash
# First query - save the session_id from response
curl -X POST "http://localhost:8000/api/v1/system-design/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Design Instagram"
  }'

# Follow-up query with same session_id
curl -X POST "http://localhost:8000/api/v1/system-design/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How would you scale this to handle 500M users?",
    "session_id": "SESSION_ID_FROM_PREVIOUS_RESPONSE"
  }'
```

### Get Conversation History

```bash
curl http://localhost:8000/api/v1/system-design/conversation/{session_id}
```

### Clear Conversation

```bash
curl -X DELETE http://localhost:8000/api/v1/system-design/conversation/{session_id}
```

## Interactive API Documentation

Visit `http://localhost:8000/docs` for Swagger UI where you can:
- View all endpoints
- Test requests interactively
- See request/response schemas
- Download OpenAPI spec

## Sample Test Queries

### 1. E-commerce Platform
```json
{
  "query": "Design an e-commerce platform like Amazon with product search, shopping cart, and payment processing",
  "include_evaluation": true,
  "context": {
    "scale": "1M products, 10M users",
    "requirements": ["search", "recommendations", "real-time inventory"]
  }
}
```

### 2. Video Streaming Service
```json
{
  "query": "Design a video streaming service like Netflix",
  "include_evaluation": true,
  "context": {
    "scale": "100M users, 4K streaming",
    "regions": "global"
  }
}
```

### 3. Real-time Chat Application
```json
{
  "query": "Design WhatsApp - a real-time messaging system with end-to-end encryption",
  "include_evaluation": true,
  "context": {
    "scale": "2B users",
    "features": ["1-to-1 chat", "group chat", "media sharing", "status updates"]
  }
}
```

## Testing the RAG Pipeline

### Initialize Vector Database
```bash
python scripts/initialize_vector_db.py
```

### Add Custom Documents
1. Create markdown/text files in `data/system_design_docs/`
2. Re-run the initialization script
3. Test retrieval with related queries

## Expected Response Structure

```json
{
  "query": "string",
  "session_id": "string (UUID)",
  "architecture": {
    "services": ["array of services"],
    "database": "string",
    "scaling_strategy": "string",
    "tradeoffs": [
      {
        "aspect": "string",
        "options": ["array"],
        "recommendation": "string",
        "considerations": ["array"]
      }
    ],
    "key_components": {"dict"},
    "data_flow": "string",
    "api_design": ["array"],
    "non_functional_requirements": {"dict"}
  },
  "explanation": "string",
  "evaluation": {
    "confidence_score": 0.85,
    "strengths": ["array"],
    "weaknesses": ["array"],
    "suggestions": ["array"],
    "hallucination_check": true,
    "completeness_score": 0.8
  },
  "token_usage": {
    "prompt_tokens": 500,
    "completion_tokens": 800,
    "total_tokens": 1300,
    "estimated_cost_usd": 0.013
  },
  "retrieved_context": ["array"],
  "timestamp": "ISO datetime"
}
```

## Troubleshooting

### Issue: "OpenAI API key not configured"
- Check `.env` file exists
- Verify `OPENAI_API_KEY` is set
- Restart the server

### Issue: "No documents found in vector store"
- Run `python scripts/initialize_vector_db.py`
- Check `data/system_design_docs/` has documents
- Verify FAISS index created in `data/vector_store/`

### Issue: 500 Internal Server Error
- Check server logs
- Verify all dependencies installed: `pip install -e .`
- Check Python version: `python --version` (need 3.12+)
