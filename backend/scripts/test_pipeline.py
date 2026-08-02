"""End-to-end smoke test for the Phase 1 pipeline.

Wires together every module built in Steps 4-6 against the real Docker
Postgres populated by Step 3 (TPC-H SF=1). Runs TPC-H Q3 — a customer × orders
× lineitem join with no indexes on the filter columns — and prints:

  1. Parsed plan nodes (from plan_parser)
  2. Detected problems (from detector)
  3. Cold/warm benchmark stats (from harness)

Run:
    python test_pipeline.py

Passing means: Postgres reachable, TPC-H loaded, all three analyzer modules
compose cleanly on real data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

# Make sibling `analyzer/` and `benchmarks/` packages importable when this
# script is run directly (i.e., `python test_pipeline.py`).
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from analyzer.plan_parser import parse_plan, run_explain
from analyzer.detector import detect_problems
from benchmarks.harness import run_benchmark


# TPC-H Query 3 — Shipping Priority. Reference query from the TPC-H spec.
# Chosen because at SF=1 with only PKs, it forces sequential scans on
# customer, orders, and lineitem and takes ~1 second — plenty for the
# detector to complain about and the harness to measure.
TPCH_Q3 = """
SELECT l_orderkey,
       sum(l_extendedprice * (1 - l_discount)) AS revenue,
       o_orderdate,
       o_shippriority
FROM customer, orders, lineitem
WHERE c_mktsegment = 'BUILDING'
  AND c_custkey = o_custkey
  AND l_orderkey = o_orderkey
  AND o_orderdate < DATE '1995-03-15'
  AND l_shipdate  > DATE '1995-03-15'
GROUP BY l_orderkey, o_orderdate, o_shippriority
ORDER BY revenue DESC, o_orderdate
LIMIT 10
"""


def _connect() -> psycopg2.extensions.connection:
    """Open a psycopg2 connection using env vars with Docker-Compose defaults."""
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "optimus"),
        password=os.getenv("PG_PASSWORD", "optimus"),
        dbname=os.getenv("PG_DB", "tpch"),
    )


def _hr(title: str) -> None:
    """Print a horizontal-rule section header."""
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def main() -> int:
    """Run the full Phase 1 pipeline and return an exit code (0 on success)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    conn = _connect()
    try:
        _hr("Query under test — TPC-H Q3 (Shipping Priority)")
        print(TPCH_Q3.strip())

        _hr("Step 1/3 — Parsed plan nodes")
        raw = run_explain(TPCH_Q3, conn)
        nodes = parse_plan(raw)
        print(f"{len(nodes)} nodes  ·  planning={raw['Planning Time']:.1f}ms  "
              f"·  execution={raw['Execution Time']:.1f}ms\n")
        for n in nodes:
            indent = "  " * n.depth
            rel = f" on {n.relation_name}" if n.relation_name else ""
            filt = f"  filter={n.filter!r}" if n.filter else ""
            print(f"{indent}- {n.node_type}{rel}  "
                  f"cost={n.startup_cost:.1f}..{n.total_cost:.1f}  "
                  f"rows(plan={n.plan_rows:,}, actual={n.actual_rows:,}, "
                  f"loops={n.actual_loops}){filt}")

        _hr("Step 2/3 — Detected problems")
        problems = detect_problems(nodes)
        if not problems:
            print("No problems detected.")
        else:
            print(f"{len(problems)} problem(s):\n")
            for p in problems:
                print(f"  [{p.severity.value:6s}] {p.type.value}")
                print(f"           {p.message}\n")

        _hr("Step 3/3 — Benchmark (10 runs)")
        result = run_benchmark(TPCH_Q3, conn, n=10)
        print(f"  cold        : {result.cold_ms:8.2f} ms")
        print(f"  warm p50    : {result.warm_p50_ms:8.2f} ms")
        print(f"  warm p95    : {result.warm_p95_ms:8.2f} ms")
        print(f"  warm min/max: {result.warm_min_ms:8.2f} / {result.warm_max_ms:.2f} ms")
        print(f"  all runs    : [" + ", ".join(f"{t:.1f}" for t in result.all_runs_ms) + "] ms")

        _hr("Pipeline OK")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
