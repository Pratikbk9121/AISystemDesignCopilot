# Setup & Error Fixes

This document contains solutions to common setup errors when running the AI System Design Copilot project.

## Current Errors Fixed

### ✅ Error 1: Missing .env file
**Error Message:** `ValueError: OpenAI API key not configured`

**Solution:**
```bash
# .env file has been created from template
# You need to add your actual API key to .env file
```

Edit the `.env` file and replace `your_openai_api_key_here` with your actual OpenAI API key:
```bash
OPENAI_API_KEY=sk-your-actual-api-key-here
```

Get your API key from: https://platform.openai.com/api-keys

### ⚠️ Error 2: Python 3.14 Compatibility Warning
**Warning Message:**
```
Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.
```

**Root Cause:** 
LangChain uses Pydantic V1 internally which has compatibility issues with Python 3.14+. This is a known issue with the current version of LangChain.

**Solutions:**

#### Option 1: Use Python 3.12 (Recommended)
The project was designed for Python 3.12+. Using Python 3.12 will avoid the Pydantic V1 warning.

```bash
# Install Python 3.12 using Homebrew
brew install python@3.12

# Create a virtual environment with Python 3.12
python3.12 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
uvicorn app.main:app --reload --port 8000
```

#### Option 2: Continue with Python 3.14 (Warning will persist)
The warning is not fatal - the application may still work, but you might encounter compatibility issues.

```bash
# Run with Python 3.14 (current setup)
python3 -m uvicorn app.main:app --reload --port 8000
```

**Note:** This is a temporary warning from LangChain. Future versions of LangChain should fully support Python 3.14.

## Quick Start (After Fixes)

1. **Set up API Key:**
   ```bash
   # Edit .env file
   nano .env  # or use your preferred editor
   
   # Add your OpenAI API key:
   OPENAI_API_KEY=sk-your-actual-key-here
   ```

2. **Initialize Vector Database (Optional but recommended):**
   ```bash
   python3 scripts/initialize_vector_db.py
   ```

3. **Run the Application:**
   ```bash
   python3 -m uvicorn app.main:app --reload --port 8000
   ```

4. **Access the API:**
   - API Documentation: http://localhost:8000/docs
   - Root Endpoint: http://localhost:8000/

## Testing the Application

Once running, test with a simple health check:
```bash
curl http://localhost:8000/api/v1/system-design/health
```

Or test the main endpoint:
```bash
curl -X POST http://localhost:8000/api/v1/system-design/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Design a URL shortener like bit.ly",
    "include_evaluation": false
  }'
```

## Remaining Steps

- [ ] Add valid OpenAI API key to `.env`
- [ ] (Optional) Use Python 3.12 to avoid compatibility warnings
- [ ] Initialize vector database with sample data
- [ ] Test application startup
- [ ] Make your first API request

## Need Help?

If you encounter other errors, check:
1. Python version: `python3 --version` (should be 3.12+)
2. Dependencies installed: `pip list | grep -E "fastapi|langchain"`
3. .env file exists and has valid API key
4. Port 8000 is not already in use: `lsof -i :8000`
