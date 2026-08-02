"""OptimusDB backend — FastAPI entry point.

Start with:
    uvicorn main:app --reload --port 8000
    # or, from anywhere:
    python -m uvicorn main:app --reload --port 8000

Assumes:
    - Postgres up:      docker compose -f ../docker-compose.yml up -d
    - TPC-H loaded:     bash scripts/load_tpch.sh
    - LLM key set:      GROQ_API_KEY in ../.env (auto-loaded via llm.client)
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Make sibling packages (analyzer, benchmarks, llm, api) importable when
# uvicorn boots this module directly.
_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.db import close_pool, init_pool
from api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup: warm the connection pool. Shutdown: close every connection."""
    init_pool(minconn=1, maxconn=8)
    yield
    close_pool()


app = FastAPI(
    title="OptimusDB — AI Query Optimizer",
    description=(
        "HTTP surface for the deterministic analyzer + LLM rewrite loop. "
        "See /docs for the OpenAPI schema."
    ),
    version="0.4.0",
    lifespan=lifespan,
)

# Phase 5 (React frontend) will run on Vite's default port. Wide-open CORS
# is fine for local dev; lock this down before deploying anywhere.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
