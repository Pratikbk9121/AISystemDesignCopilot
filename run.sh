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

# Check if vector database is initialized
if [ ! -d "data/vector_store/faiss_index" ]; then
    echo "📚 Vector database not initialized."
    read -p "Would you like to initialize it now with sample data? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        python scripts/initialize_vector_db.py
    fi
fi

# Start the server
echo ""
echo "✅ Starting FastAPI server on http://localhost:8000"
echo "📖 API Documentation: http://localhost:8000/docs"
echo ""
uvicorn app.main:app --reload --port 8000
