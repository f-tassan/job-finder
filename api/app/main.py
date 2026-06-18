"""FastAPI application entrypoint.

Phase 1: auth, users (admin), profile/answer-bank, CVs, applications. All
business routes are mounted under the routers below; the reverse proxy serves
them at /api/*.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    applications,
    auth,
    cvs,
    jobs,
    profile,
    searches,
    users,
)
from app.seed import seed_first_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed the first admin from env if the DB has no users yet.
    await seed_first_user()
    yield


app = FastAPI(title="job-finder API", version="0.1.0", lifespan=lifespan)

# Same-origin in production (Caddy serves web + proxies /api). Permissive here for
# dev/LAN access; auth is Bearer-token based, so credentials aren't cookie-bound.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Used by the container healthcheck and the web app."""
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(profile.router)
app.include_router(cvs.router)
app.include_router(applications.router)
app.include_router(searches.router)
app.include_router(jobs.router)
