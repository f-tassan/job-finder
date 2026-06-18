# FastAPI + Celery image (one image, multiple commands via docker-compose).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# procps: pgrep for the beat healthcheck. curl: convenience/healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends procps curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .
# CPU-only torch (avoids the multi-GB CUDA wheel), then the app + ML extra for
# local sentence-transformers embeddings.
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install ".[ml]" \
    && chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
