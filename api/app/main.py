"""FastAPI application entrypoint.

Phase 0 exposes only GET /health. Routers are wired in later phases.
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="job-finder API", version="0.0.0")


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Used by the container healthcheck and the web app."""
    return {"status": "ok"}
