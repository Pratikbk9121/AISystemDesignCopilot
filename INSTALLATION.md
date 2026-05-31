# Installation Guide - LangChain RAG System

## Quick Start

### Step 1: Install Dependencies

```bash
# Make sure you're using Python 3.9+
python3 --version

# Install all dependencies
python3 -m pip install -r requirements.txt
```

### Step 2: Verify Installation

Run the automated setup script:

```bash
./setup_langchain.sh
```

**OR** manually verify:

```bash
python3 -c "from langchain_huggingface import HuggingFaceEmbeddings; print('OK')"
```

---

## Troubleshooting

### Issue: `ModuleNotFoundError: No module named 'langchain_huggingface'`

**Solution 1: Ensure you're using the correct Python**

```bash
# Check which Python you're using
which python3
python3 --version

# Install to the correct Python
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

**Solution 2: Install packages individually**

```bash
python3 -m pip install langchain>=0.3.0
python3 -m pip install langchain-community>=0.3.0
python3 -m pip install langchain-huggingface>=0.1.0
python3 -m pip install langchain-openai>=0.2.0
python3 -m pip install langchain-qdrant>=0.2.0
```

**Solution 3: Check your IDE/Environment**

If you're using VS Code, PyCharm, or Jupyter:
1. Make sure the interpreter is set to the same Python 3 that has the packages
2. Restart your IDE/kernel
3. Try running from the command line first

---

### Issue: Import hangs or takes too long

**Reason**: First import downloads the HuggingFace model (~438MB)

**Solution**: Be patient on first run. Subsequent imports will be fast.

```bash
# Monitor the download
python3 -c "from langchain_huggingface import HuggingFaceEmbeddings; emb = HuggingFaceEmbeddings(model_name='BAAI/bge-base-en-v1.5')"
```

---

### Issue: Running from different directory

**Solution**: Always run from the project root

```bash
cd /Users/pbkansara/AISystemDesignCopilot
python3 test_langchain_migration.py
```

---

## Manual Testing

### Test 1: Import LangChain packages

```bash
python3 << 'EOF'
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
print("All imports successful!")
EOF
```

### Test 2: Test embeddings

```bash
python3 << 'EOF'
import sys
sys.path.insert(0, '.')
from app.core.rag.embeddings import EmbeddingGenerator

emb = EmbeddingGenerator(provider="huggingface")
vec = emb.generate_embedding("Test text")
print(f"Embedding shape: {vec.shape}")
print("Success!")
EOF
```

### Test 3: Run full migration test

```bash
python3 test_langchain_migration.py
```

---

## Using Virtual Environment (Recommended)

If you want to isolate dependencies:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt

# Run tests
python test_langchain_migration.py

# Deactivate when done
deactivate
```

---

## Environment Setup

### Option 1: System-wide installation (Current)

```bash
python3 -m pip install -r requirements.txt
python3 test_langchain_migration.py
```

### Option 2: Virtual environment (Recommended for development)

See section above.

### Option 3: Using the project's existing environment

If you had a virtual environment before:

```bash
# Find and activate it
source venv/bin/activate  # or wherever it is

# Update dependencies
pip install -r requirements.txt
```

---

## Next Steps After Installation

1. **Test the system**:
   ```bash
   python3 test_langchain_migration.py
   ```

2. **Initialize vector database**:
   ```bash
   python3 scripts/initialize_qdrant.py
   ```

3. **Run the demo**:
   ```bash
   python3 scripts/demo_rag_pipeline.py
   ```

4. **Start the API server**:
   ```bash
   python3 -m uvicorn app.main:app --reload
   ```

---

## Getting Help

If you continue to have issues:

1. Check Python version: `python3 --version` (need 3.9+)
2. Check installed packages: `python3 -m pip list | grep langchain`
3. Verify you're in the project directory: `pwd`
4. Check the error message carefully - it often tells you what's missing

Common package list to verify:
```
langchain
langchain-community
langchain-core
langchain-huggingface
langchain-openai
langchain-qdrant
langchain-text-splitters
```
