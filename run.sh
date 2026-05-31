#!/bin/bash

# AI System Design Copilot - Run Script

echo "🚀 Starting AI System Design Copilot..."
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Virtual environment not found. Creating..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Check if dependencies are installed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "📦 Installing dependencies..."
    pip install -e .
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    echo "Please copy .env.example to .env and configure your API keys."
    echo ""
    echo "cp .env.example .env"
    exit 1
fi

# Note: Qdrant runs in-memory by default (no persistence check needed)
# To initialize with sample data, run: python scripts/initialize_qdrant.py

# Start the server
echo ""
echo "✅ Starting FastAPI server on http://localhost:8000"
echo "📖 API Documentation: http://localhost:8000/docs"
echo ""
uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 25
