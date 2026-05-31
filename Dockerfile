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

# Run
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
