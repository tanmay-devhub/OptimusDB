"""Benchmark harness.

Runs a query N times, splits the first execution (cold cache) from the
warm-cache steady state, and reports percentile timings. This is what
`POST /optimize` will call twice — once for the original query, once for
the LLM's rewrite — so we can show "50% faster" claims with numbers, not
vibes.

Cold vs. warm here is a client-side approximation: we don't restart the
Postgres process or flush OS page cache between runs. Instead we treat
run #1 as "cold" (nothing cached yet) and average runs #4..N as "warm"
(shared_buffers + OS cache populated). Runs #2 and #3 are discarded as
warmup — they usually still contain JIT compilation and plan cache misses.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BenchmarkResult:
    """Timing summary from `run_benchmark`. All timings are milliseconds."""

    n: int
    cold_ms: float
    warm_p50_ms: float
    warm_p95_ms: float
    warm_min_ms: float
    warm_max_ms: float
    # Every run's wall-clock time, in execution order — useful for spotting
    # trends (JIT warmup, cache thrash) that summary stats hide.
    all_runs_ms: list[float] = field(default_factory=list)


def run_benchmark(query: str, conn: Any, n: int = 10) -> BenchmarkResult:
    """Execute ``query`` ``n`` times and return timing stats.

    Layout:
      * run  1        → cold-cache sample (recorded)
      * runs 2..3     → warmup (discarded)
      * runs 4..n     → warm-cache samples (percentiles computed from here)

    So ``n`` must be at least 4 to yield one warm sample.

    Args:
        query: Read-only SQL to benchmark. Do not pass DDL/DML.
        conn:  An open psycopg2 connection.
        n:     Total number of runs, default 10.

    Returns:
        A `BenchmarkResult` with cold, warm-p50, warm-p95, warm-min, warm-max,
        and the full per-run timing list.
    """
    if n < 4:
        raise ValueError("n must be >= 4 (1 cold + 2 warmup + >=1 warm sample)")

    timings: list[float] = []
    with conn.cursor() as cur:
        for _ in range(n):
            start = time.perf_counter_ns()
            cur.execute(query)
            # Consume the result set so we measure end-to-end, including
            # server serialization + client deserialization.
            cur.fetchall()
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            timings.append(elapsed_ms)

    cold_ms = timings[0]
    warm = timings[3:]  # discard cold + 2 warmup
    warm_sorted = sorted(warm)

    return BenchmarkResult(
        n=n,
        cold_ms=cold_ms,
        warm_p50_ms=_percentile(warm_sorted, 50),
        warm_p95_ms=_percentile(warm_sorted, 95),
        warm_min_ms=min(warm),
        warm_max_ms=max(warm),
        all_runs_ms=timings,
    )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile on an already-sorted list.

    Matches ``numpy.percentile(..., interpolation="linear")``. For the
    small sample sizes typical here (N ~= 7), this is more stable than
    nearest-rank at N=1..3.
    """
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_values[0]
    k = (n - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, n - 1)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


# -----------------------------------------------------------------------------
# Smoke test — benchmark a filtered scan on the 150k-row customer table.
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
    try:
        query = "SELECT count(*) FROM customer WHERE c_mktsegment = 'BUILDING'"
        print(f"Benchmarking: {query}\n")
        result = run_benchmark(query, conn, n=10)
        print(f"  runs        : {result.n}")
        print(f"  cold        : {result.cold_ms:8.2f} ms")
        print(f"  warm p50    : {result.warm_p50_ms:8.2f} ms")
        print(f"  warm p95    : {result.warm_p95_ms:8.2f} ms")
        print(f"  warm min/max: {result.warm_min_ms:8.2f} / {result.warm_max_ms:.2f} ms")
        print("  all runs    : [" + ", ".join(f"{t:.2f}" for t in result.all_runs_ms) + "] ms")
    finally:
        conn.close()
