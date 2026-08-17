"""Phase 10.3 smoke test - /optimize mode dichotomy.

Runs the classic correlated-subquery demo through /optimize twice:

    1. mode="hypothetical" - expects cost_ratio populated, no benchmarks,
       zero cleanup_leaks (nothing to leak), no permanent optimusdb_tmp_
       indexes visible from a second connection.
    2. mode="measure"      - expects speedup populated, benchmarks present,
       cleanup_leaks empty (physical indexes dropped).

The test drives the running FastAPI server via HTTP (uvicorn on :8000)
so the schema + route wiring are exercised end-to-end. Skip if the
server is not reachable.

Requires:
    * docker compose up postgres (with hypopg installed)
    * GROQ_API_KEY in project/.env
    * python -m uvicorn main:app --reload --port 8000  from backend/

Exit 0 on success, 1 on any check failure, 2 if the server is down.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import psycopg2

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


API_BASE = os.getenv("OPTIMUSDB_API", "http://localhost:8000")

# Same demo query as test_optimize.py - a correlated subquery in the
# SELECT list, a shape both the LLM's rewrite (JOIN) and its suggested
# indexes can plausibly improve.
DEMO_QUERY = """
SELECT o_orderkey,
       o_totalprice,
       (SELECT c_name FROM customer WHERE c_custkey = o_custkey) AS customer_name,
       (SELECT c_mktsegment FROM customer WHERE c_custkey = o_custkey) AS segment
FROM orders
WHERE o_orderdate BETWEEN DATE '1996-01-01' AND DATE '1996-01-31'
""".strip()


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def _connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "optimus"),
        password=os.getenv("PG_PASSWORD", "optimus"),
        dbname=os.getenv("PG_DB", "tpch"),
    )


def _tmp_index_count() -> int:
    """From a fresh connection, count physical optimusdb_tmp_ indexes."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM pg_indexes WHERE indexname LIKE 'optimusdb_tmp_%'"
            )
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def _hr(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def _check(cond: bool, ok_msg: str, fail_msg: str, failures: list[str]) -> None:
    if cond:
        print(f"  [OK]   {ok_msg}")
    else:
        print(f"  [FAIL] {fail_msg}")
        failures.append(fail_msg)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # Server reachability probe.
    try:
        with urllib.request.urlopen(f"{API_BASE}/health", timeout=5) as r:
            r.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Backend unreachable at {API_BASE}: {exc}")
        print("Start it: cd backend && python -m uvicorn main:app --port 8000")
        return 2

    failures: list[str] = []
    baseline_leak = _tmp_index_count()
    if baseline_leak != 0:
        print(
            f"WARN: {baseline_leak} optimusdb_tmp_ index(es) present before test - "
            "these are pre-existing leaks, not caused by this test."
        )

    # ------------------------------------------------------------------ #
    # 1. Hypothetical mode
    # ------------------------------------------------------------------ #
    _hr("Phase 10.3 - /optimize mode='hypothetical'")
    try:
        hypo = _post("/optimize", {"query": DEMO_QUERY, "mode": "hypothetical"})
    except Exception as exc:
        print(f"  [FAIL] /optimize hypothetical raised: {exc}")
        return 1
    print(
        f"  valid={hypo.get('valid')}  unchanged={hypo.get('unchanged')}  "
        f"mode={hypo.get('mode')}  cost_ratio={hypo.get('cost_ratio')}"
    )
    _check(hypo.get("mode") == "hypothetical",
           "response.mode == 'hypothetical'",
           f"response.mode={hypo.get('mode')!r}, expected 'hypothetical'",
           failures)
    _check(hypo.get("original_benchmark") is None,
           "original_benchmark is None (no benchmarking in hypothetical mode)",
           "original_benchmark was set in hypothetical mode",
           failures)
    _check(hypo.get("rewrite_benchmark") is None,
           "rewrite_benchmark is None (no benchmarking in hypothetical mode)",
           "rewrite_benchmark was set in hypothetical mode",
           failures)
    _check(hypo.get("speedup") is None,
           "speedup is None (currency is cost_ratio in hypothetical mode)",
           "speedup was set in hypothetical mode",
           failures)
    if hypo.get("valid") and not hypo.get("unchanged"):
        _check(hypo.get("cost_ratio") is not None,
               f"cost_ratio present ({hypo.get('cost_ratio')})",
               "cost_ratio missing on a valid, changed rewrite",
               failures)
        _check(hypo.get("original_total_cost") is not None,
               "original_total_cost populated",
               "original_total_cost missing",
               failures)
    _check(hypo.get("cleanup_leaks") == [],
           "cleanup_leaks == [] (hypothetical mode cannot leak)",
           f"cleanup_leaks={hypo.get('cleanup_leaks')!r}, expected []",
           failures)
    # Every applied_indexes entry either has an hypopg_oid or is a failure.
    applied = hypo.get("applied_indexes") or []
    for idx in applied:
        if idx.get("applied") and idx.get("hypopg_oid") is None:
            failures.append(f"applied hypothetical index {idx['tmp_name']} has no hypopg_oid")
            print(f"  [FAIL] {idx['tmp_name']} applied but hypopg_oid is None")
    if applied and all(
        (not idx.get("applied")) or idx.get("hypopg_oid") is not None
        for idx in applied
    ):
        print(f"  [OK]   all {len(applied)} suggestion(s) have hypopg_oid or an error")

    # No new physical tmp indexes should exist post-hypothetical.
    post_hypo_leak = _tmp_index_count()
    _check(post_hypo_leak <= baseline_leak,
           f"no new optimusdb_tmp_ indexes created ({baseline_leak} -> {post_hypo_leak})",
           f"physical indexes created in hypothetical mode ({baseline_leak} -> {post_hypo_leak})",
           failures)

    # ------------------------------------------------------------------ #
    # 2. Measure mode (default)
    # ------------------------------------------------------------------ #
    _hr("Phase 10.3 - /optimize mode='measure' (default)")
    try:
        meas = _post("/optimize", {"query": DEMO_QUERY, "mode": "measure"})
    except Exception as exc:
        print(f"  [FAIL] /optimize measure raised: {exc}")
        return 1
    print(
        f"  valid={meas.get('valid')}  unchanged={meas.get('unchanged')}  "
        f"mode={meas.get('mode')}  speedup={meas.get('speedup')}"
    )
    _check(meas.get("mode") == "measure",
           "response.mode == 'measure'",
           f"response.mode={meas.get('mode')!r}, expected 'measure'",
           failures)
    if meas.get("valid") and not meas.get("unchanged"):
        _check(meas.get("original_benchmark") is not None,
               "original_benchmark populated (measure mode benches)",
               "original_benchmark missing in measure mode",
               failures)
        _check(meas.get("rewrite_benchmark") is not None,
               "rewrite_benchmark populated (measure mode benches)",
               "rewrite_benchmark missing in measure mode",
               failures)
        _check(meas.get("speedup") is not None,
               f"speedup populated ({meas.get('speedup')})",
               "speedup missing on a valid, changed rewrite",
               failures)
    _check(meas.get("cost_ratio") is None,
           "cost_ratio is None (measure mode uses speedup currency)",
           f"cost_ratio was set in measure mode: {meas.get('cost_ratio')}",
           failures)
    _check(meas.get("cleanup_leaks") == [],
           "cleanup_leaks == [] (physical indexes cleaned up)",
           f"cleanup_leaks={meas.get('cleanup_leaks')!r}, expected []",
           failures)

    post_meas_leak = _tmp_index_count()
    _check(post_meas_leak <= baseline_leak,
           f"no persistent optimusdb_tmp_ indexes after measure "
           f"({baseline_leak} -> {post_meas_leak})",
           f"physical indexes leaked in measure mode "
           f"({baseline_leak} -> {post_meas_leak})",
           failures)

    _hr("Phase 10.3 report")
    if failures:
        print(f"  FAILED ({len(failures)} check(s)):")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  PASSED - hypothetical and measure modes each return their expected fields.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
