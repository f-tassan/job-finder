# FastAPI + Celery image (one image, multiple commands via docker-compose).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# procps: pgrep for the beat healthcheck. curl: healthchecks.
# The libpango/cairo/gdk-pixbuf stack + fonts are WeasyPrint's native deps for
# ATS PDF rendering (DejaVu for Latin, Noto for Arabic names).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        procps curl \
        libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
        libcairo2 libffi8 shared-mime-info \
        fonts-dejavu-core fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch (avoids the multi-GB CUDA wheel) on its OWN layer, BEFORE copying
# the app source — so editing code never busts this layer and re-downloads the
# 192 MB wheel. A BuildKit pip cache mount + retries make the download resumable
# and survivable on a flaky/throttled connection.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install --retries 10 --timeout 180 \
        --index-url https://download.pytorch.org/whl/cpu torch

# App + ML extra (sentence-transformers, etc.). Needs the source, so it follows
# the copy — but the cache mount keeps already-downloaded wheels, so a rebuild
# after a code edit reinstalls from cache without re-downloading.
COPY . .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 180 ".[ml]" \
    && chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
