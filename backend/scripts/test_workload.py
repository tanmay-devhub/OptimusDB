"""Phase 2 end-to-end demo — simulate a mixed workload, then let the
batch analyzer discover the slowest queries and their problems.

This is the "app runs against your production Postgres for a while,
then tells you what's costing you time" experience, minus a real
production Postgres.

Run:
    python test_workload.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from analyzer.batch import analyze_workload
from analyzer.workload import reset_stats


# A synthetic workload with varied cost and shape. Some queries have
# literal filters (will be normalized by pg_stat_statements and skipped
# during re-analysis); some don't (will be analyzed end-to-end).
WORKLOAD = [
    # (SQL, calls) — repeat count simulates hot vs cold queries.
    ("SELECT count(*) FROM lineitem", 2),
    ("SELECT count(*) FROM lineitem WHERE l_shipdate > DATE '1995-01-01'", 5),
    ("SELECT c_mktsegment, count(*) FROM customer GROUP BY c_mktsegment", 4),
    ("SELECT count(*) FROM orders WHERE o_orderstatus = 'F'", 3),
    ("SELECT n_name, count(*) FROM nation JOIN supplier ON n_nationkey=s_nationkey GROUP BY n_name", 2),
    ("SELECT count(*) FROM orders WHERE o_totalprice > 100000", 6),
]


def _connect() -> psycopg2.extensions.connection:
    """Open a psycopg2 connection using env vars with Docker-Compose defaults."""
    conn = psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "optimus"),
        password=os.getenv("PG_PASSWORD", "optimus"),
        dbname=os.getenv("PG_DB", "tpch"),
    )
    conn.autocommit = True
    return conn


def _hr(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def _seed_workload(conn: psycopg2.extensions.connection) -> None:
    """Run each WORKLOAD query its ``calls`` times to populate pg_stat_statements."""
    total_calls = sum(c for _, c in WORKLOAD)
    print(f"Seeding {len(WORKLOAD)} distinct queries "
          f"({total_calls} total executions)... ", end="", flush=True)
    with conn.cursor() as cur:
        for sql, times in WORKLOAD:
            for _ in range(times):
                cur.execute(sql)
                cur.fetchall()
    print("done.")


def main() -> int:
    """Reset stats, run the simulated workload, discover slow queries, print report."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    conn = _connect()
    try:
        _hr("Phase 2 — workload-driven analysis")
        reset_stats(conn)
        _seed_workload(conn)

        reports = analyze_workload(conn, n=10)
        analyzed = sum(1 for r in reports if r.analysis_skipped_reason is None)
        with_problems = sum(1 for r in reports if r.problems)
        total_problems = sum(len(r.problems) for r in reports)

        _hr(f"Ranked report — {len(reports)} slow queries "
            f"({analyzed} analyzed, {with_problems} with problems, "
            f"{total_problems} total issues)")

        for i, r in enumerate(reports, 1):
            s = r.slow
            print(f"\n  #{i}  total={s.total_exec_ms:8.2f}ms  "
                  f"calls={s.calls:>3}  mean={s.mean_exec_ms:6.2f}ms")
            print(f"      {s.query}")
            if r.analysis_skipped_reason:
                print(f"      · skipped: {r.analysis_skipped_reason}")
            elif not r.problems:
                print(f"      · {r.plan_nodes_count} plan nodes, no problems detected")
            else:
                print(f"      · {r.plan_nodes_count} plan nodes, {len(r.problems)} problem(s):")
                for p in r.problems:
                    print(f"          [{p.severity.value:6s}] {p.type.value}")
                    print(f"                   {p.message}")

        _hr("Phase 2 pipeline OK")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
