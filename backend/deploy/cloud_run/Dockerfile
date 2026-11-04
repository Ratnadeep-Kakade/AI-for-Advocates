FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 poppler-utils libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY . /app
# CPU-only torch first: the default wheel pulls multi-GB CUDA packages that a
# CPU Cloud Run service can never use (image size, memory, cold start).
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-rag.txt
ENV PORT=8080
CMD ["sh", "-c", "uvicorn cicero.rag_worker.service:app --host 0.0.0.0 --port ${PORT:-8080}"]
