"""Postgres connection pool + FastAPI dependency.

One shared psycopg2 pool per app instance. Each request checks a
connection out via the ``get_conn`` dependency and returns it on the way
out. autocommit is on so EXPLAIN, benchmarks, and pg_stat_statements
reads don't accidentally leave transactions dangling.
"""
from __future__ import annotations

import os
from typing import Generator

import psycopg2
from psycopg2.pool import SimpleConnectionPool


_POOL: SimpleConnectionPool | None = None


def init_pool(minconn: int = 1, maxconn: int = 8) -> None:
    """Create the process-wide pool. Called once at app startup."""
    global _POOL
    if _POOL is not None:
        return
    _POOL = SimpleConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "optimus"),
        password=os.getenv("PG_PASSWORD", "optimus"),
        dbname=os.getenv("PG_DB", "tpch"),
    )


def close_pool() -> None:
    """Close every connection in the pool. Called once at app shutdown."""
    global _POOL
    if _POOL is not None:
        _POOL.closeall()
        _POOL = None


def get_conn() -> Generator[psycopg2.extensions.connection, None, None]:
    """FastAPI dependency: yield a pooled connection, return it after the request."""
    if _POOL is None:
        raise RuntimeError("Connection pool not initialized. Call init_pool() first.")
    conn = _POOL.getconn()
    conn.autocommit = True
    try:
        yield conn
    finally:
        # Reset autocommit state before returning so nothing leaks.
        try:
            conn.rollback()
        except Exception:
            pass
        _POOL.putconn(conn)
