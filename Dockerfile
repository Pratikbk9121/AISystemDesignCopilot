# Base image
FROM python:3.12-slim

WORKDIR /app

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Non-root user (HF Spaces requirement: UID 1000 with writable homedir for caches)
RUN useradd -m -u 1000 user
ENV HF_HOME=/home/user/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/user/.cache/huggingface/sentence-transformers

# App source
COPY --chown=user:user . /app
RUN chown -R user:user /app

USER user

# Pre-download embedding model into the user's HF cache so first request skips the 440MB pull
RUN python -c "from langchain_huggingface import HuggingFaceEmbeddings; HuggingFaceEmbeddings(model_name='BAAI/bge-base-en-v1.5', model_kwargs={'device':'cpu'})"

# Prefetch cross-encoder reranker weights so first-query latency is fast (Wave 2D).
# ~570MB pulled into SENTENCE_TRANSFORMERS_HOME so live containers never wait.
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=512)"

# Prefetch fastembed BM25 sparse model so hybrid retrieval is hot at boot.
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding('Qdrant/bm25')"

# Bake the Qdrant index into the image so the live container has knowledge
# from t=0 — no "did bootstrap succeed at boot?" risk. We force on-disk mode
# here because the in-memory index would vanish when this RUN step exits.
# TEKION_LLM_KEY + API_AUTH_ENABLED=false satisfy Settings invariants purely
# for this build step; the script only touches Qdrant + the embedding model
# and never serves HTTP or calls the LLM. The real key and auth config are
# injected at runtime from HF Spaces secrets.
ENV QDRANT_USE_MEMORY=false
ENV QDRANT_PATH=/app/data/vector_store/qdrant_data
RUN TEKION_LLM_KEY=build-time-unused API_AUTH_ENABLED=false \
    python scripts/initialize_qdrant.py --clear

# Run
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
