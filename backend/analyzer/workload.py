"""Workload collector.

Reads pg_stat_statements to surface the queries that hurt the most.
Ranking is by ``total_exec_time`` (= mean_exec_time × calls), so a fast
query hit a million times can rank above a slow one hit twice — which
matches how real workloads actually bleed time.

Note on query text: pg_stat_statements always normalizes literal values
into ``$1, $2, ...`` placeholders (that's how it collapses many concrete
calls into one row). Re-EXPLAIN'ing those requires knowing the parameter
types; the batch analyzer handles that gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SlowQuery:
    """One row from pg_stat_statements, promoted to a typed record."""

    queryid: int
    query: str            # normalized text — may contain $1, $2, ... placeholders
    calls: int
    total_exec_ms: float  # sum across every call
    mean_exec_ms: float
    stddev_exec_ms: float
    rows: int             # total rows returned across every call


def top_slow_queries(
    conn: Any,
    n: int = 10,
    min_calls: int = 1,
) -> list[SlowQuery]:
    """Return the top-N queries by total execution time.

    Filters out queries we ourselves generate during analysis (EXPLAIN,
    reads against pg_stat_statements) and system-catalog probes — those
    would otherwise dominate a fresh install's stats.

    Args:
        conn:      Open psycopg2 connection.
        n:         Max number of queries to return.
        min_calls: Ignore queries called fewer than this many times.
                   Useful to filter one-off queries during dev.
    """
    sql = """
        SELECT queryid,
               query,
               calls,
               total_exec_time,
               mean_exec_time,
               stddev_exec_time,
               rows
        FROM pg_stat_statements
        WHERE calls >= %s
          AND query NOT ILIKE 'EXPLAIN%%'
          AND query NOT ILIKE '%%pg_stat_statements%%'
          AND query NOT ILIKE '%%pg_catalog.%%'
          AND query NOT ILIKE '%%information_schema.%%'
        ORDER BY total_exec_time DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (min_calls, n))
        rows = cur.fetchall()
    return [
        SlowQuery(
            queryid=r[0],
            query=r[1],
            calls=r[2],
            total_exec_ms=float(r[3]),
            mean_exec_ms=float(r[4]),
            stddev_exec_ms=float(r[5]),
            rows=int(r[6]),
        )
        for r in rows
    ]


def reset_stats(conn: Any) -> None:
    """Zero pg_stat_statements. Use between benchmark scenarios or demos."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_stat_statements_reset()")
    conn.commit()


# -----------------------------------------------------------------------------
# Smoke test — reset stats, run three seed queries, print the top-N.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import sys
    import psycopg2

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    conn = psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "optimus"),
        password=os.getenv("PG_PASSWORD", "optimus"),
        dbname=os.getenv("PG_DB", "tpch"),
    )
    conn.autocommit = True
    try:
        reset_stats(conn)
        # Seed three different queries at varying hit counts.
        seeds = [
            ("SELECT count(*) FROM lineitem", 3),
            ("SELECT count(*) FROM orders WHERE o_orderpriority = '1-URGENT'", 5),
            ("SELECT count(*) FROM customer WHERE c_acctbal > 5000", 2),
        ]
        with conn.cursor() as cur:
            for q, times in seeds:
                for _ in range(times):
                    cur.execute(q)
                    cur.fetchall()

        top = top_slow_queries(conn, n=5)
        print(f"Top {len(top)} slow queries (by total time):\n")
        for i, s in enumerate(top, 1):
            print(f"  #{i}  queryid={s.queryid}")
            print(f"      calls={s.calls}  "
                  f"mean={s.mean_exec_ms:.2f}ms  "
                  f"total={s.total_exec_ms:.2f}ms  "
                  f"rows={s.rows:,}")
            print(f"      query: {s.query}\n")
    finally:
        conn.close()
