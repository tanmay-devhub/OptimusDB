"""Phase 3 end-to-end demo — analyze → LLM rewrite → benchmark both.

Pipeline:
    1. Parse the plan for a hand-picked query with a known anti-pattern.
    2. Run the detector.
    3. Ask the LLM (Groq / Llama 3.3 70B) to rewrite it.
    4. Validate the rewrite parses (already done inside optimize_query).
    5. Benchmark original + rewrite.
    6. Print side-by-side with a speedup ratio.

Run:
    python test_optimize.py

Requires GROQ_API_KEY in project/.env (loaded automatically).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from analyzer.detector import detect_problems
from analyzer.plan_parser import parse_plan, run_explain
from benchmarks.harness import run_benchmark
from llm.optimizer import optimize_query


# A correlated subquery in the SELECT list — classic anti-pattern.
# Postgres often can't unnest these cleanly, so the subquery runs once
# per outer row. Turning it into an explicit JOIN lets the planner pick
# a hash join and slash execution time.
DEMO_QUERY = """
SELECT o_orderkey,
       o_totalprice,
       (SELECT c_name FROM customer WHERE c_custkey = o_custkey) AS customer_name,
       (SELECT c_mktsegment FROM customer WHERE c_custkey = o_custkey) AS segment
FROM orders
WHERE o_orderdate BETWEEN DATE '1996-01-01' AND DATE '1996-01-31'
""".strip()


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
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def main() -> int:
    """Full analyze → optimize → benchmark demo, exit 0 on success."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    conn = _connect()
    try:
        _hr("Phase 3 — LLM-driven query optimization")
        print("Query under test:")
        print(f"  {DEMO_QUERY.replace(chr(10), chr(10) + '  ')}\n")

        # --- 1. Analyze -------------------------------------------------
        _hr("Step 1/4 — Analyze")
        raw = run_explain(DEMO_QUERY, conn)
        nodes = parse_plan(raw)
        problems = detect_problems(nodes)
        print(f"{len(nodes)} plan nodes, {len(problems)} problem(s), "
              f"execution={raw['Execution Time']:.1f}ms")
        for p in problems:
            print(f"  [{p.severity.value:6s}] {p.type.value}: {p.message}")

        # --- 2. Ask the LLM --------------------------------------------
        _hr("Step 2/4 — LLM rewrite (Groq / Llama 3.3 70B)")
        rewrite = optimize_query(DEMO_QUERY, problems, nodes, conn)
        print(f"latency={rewrite.llm_response.latency_ms:.0f}ms   "
              f"tokens={rewrite.llm_response.input_tokens}→"
              f"{rewrite.llm_response.output_tokens}   "
              f"valid={rewrite.valid}   unchanged={rewrite.unchanged}")
        if not rewrite.valid:
            print(f"\nRewrite failed to validate:\n  {rewrite.validation_error}")
            print("\nRAW REWRITE:")
            print(rewrite.rewritten_sql)
            return 1
        if rewrite.unchanged:
            print("\nLLM returned the query unchanged — nothing to benchmark.")
            return 0

        print("\nORIGINAL:")
        for line in rewrite.original_sql.splitlines():
            print(f"  {line}")
        print("\nREWRITE:")
        for line in rewrite.rewritten_sql.splitlines():
            print(f"  {line}")

        # --- 3. Benchmark both -----------------------------------------
        _hr("Step 3/4 — Benchmark (10 runs each)")
        print("Benchmarking original... ", end="", flush=True)
        orig = run_benchmark(rewrite.original_sql, conn, n=10)
        print(f"warm p50 = {orig.warm_p50_ms:.2f}ms")
        print("Benchmarking rewrite...  ", end="", flush=True)
        new = run_benchmark(rewrite.rewritten_sql, conn, n=10)
        print(f"warm p50 = {new.warm_p50_ms:.2f}ms")

        # --- 4. Verdict -------------------------------------------------
        _hr("Step 4/4 — Verdict")
        speedup = orig.warm_p50_ms / new.warm_p50_ms if new.warm_p50_ms > 0 else 0
        print(f"                 cold       warm p50   warm p95")
        print(f"  original  {orig.cold_ms:8.2f}   {orig.warm_p50_ms:8.2f}   {orig.warm_p95_ms:8.2f}")
        print(f"  rewrite   {new.cold_ms:8.2f}   {new.warm_p50_ms:8.2f}   {new.warm_p95_ms:8.2f}")
        print()
        if speedup > 1.05:
            print(f"  → rewrite is {speedup:.2f}x FASTER (warm p50)")
        elif speedup < 0.95:
            print(f"  → rewrite is {1/speedup:.2f}x SLOWER (warm p50)")
        else:
            print(f"  → rewrite is neutral (speedup {speedup:.2f}x, within noise)")

        _hr("Phase 3 pipeline OK")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
