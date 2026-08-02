"""Batch analyzer.

Fans the top-N slow queries from the workload collector through the same
`run_explain → parse_plan → detect_problems` chain that the interactive
analyze endpoint will use. Produces a ranked list of ``WorkloadReport``
so the UI (and Phase 4 API) can show:

    "These 10 queries cost you 47 seconds last hour. Six have missing
     indexes. Three have row-estimate errors. Click any to drill in."

Queries whose stored text still contains ``$N`` placeholders can't be
EXPLAIN'd without concrete values — those come through with
``analysis_skipped_reason`` set, stats intact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    from .plan_parser import parse_plan, run_explain
    from .detector import Problem, detect_problems
    from .workload import SlowQuery, top_slow_queries
except ImportError:  # pragma: no cover — direct-script convenience
    from plan_parser import parse_plan, run_explain
    from detector import Problem, detect_problems
    from workload import SlowQuery, top_slow_queries


@dataclass
class WorkloadReport:
    """One slow query plus its analyzer output (or the reason we skipped)."""

    slow: SlowQuery
    problems: list[Problem] = field(default_factory=list)
    plan_nodes_count: int = 0
    analysis_skipped_reason: Optional[str] = None


_PARAM_RE = re.compile(r"\$\d+")


def analyze_workload(
    conn: Any,
    n: int = 10,
    min_calls: int = 1,
) -> list[WorkloadReport]:
    """Fetch top-N slow queries and analyze each one that we safely can.

    Analysis is skipped (with a reason) if the query text is parameterized
    (contains ``$N``) or is not a SELECT — because EXPLAIN ANALYZE on a
    DML statement would actually execute it and mutate the database.

    Args:
        conn:      Open psycopg2 connection.
        n:         Number of slow queries to pull.
        min_calls: Ignore queries called fewer than this many times.

    Returns:
        Reports in the same rank order as ``top_slow_queries``.
    """
    reports: list[WorkloadReport] = []
    for slow in top_slow_queries(conn, n=n, min_calls=min_calls):
        report = WorkloadReport(slow=slow)

        if _PARAM_RE.search(slow.query):
            report.analysis_skipped_reason = (
                "query is parameterized ($N) — needs concrete values to EXPLAIN"
            )
        elif not slow.query.lstrip().upper().startswith("SELECT"):
            report.analysis_skipped_reason = (
                "not a SELECT — EXPLAIN ANALYZE would execute the statement"
            )
        else:
            try:
                raw = run_explain(slow.query, conn)
                nodes = parse_plan(raw)
                report.plan_nodes_count = len(nodes)
                report.problems = detect_problems(nodes)
            except Exception as exc:
                report.analysis_skipped_reason = (
                    f"EXPLAIN failed: {type(exc).__name__}: {exc}"
                )
                # Failed EXPLAIN can leave the transaction in an aborted state.
                try:
                    conn.rollback()
                except Exception:
                    pass

        reports.append(report)
    return reports


# -----------------------------------------------------------------------------
# Smoke test — seed a mix of literal-free and literal-bearing queries so
# both code paths (analyzed vs skipped) show up in the report.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import sys
    import psycopg2

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        from .workload import reset_stats
    except ImportError:
        from workload import reset_stats

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
        seeds = [
            # Literal-free — pg_stat_statements keeps text intact, we can re-EXPLAIN.
            ("SELECT count(*) FROM lineitem", 2),
            ("SELECT c_mktsegment, count(*) FROM customer GROUP BY c_mktsegment", 3),
            # These get their literals normalized to $1 — analyzer will skip.
            ("SELECT count(*) FROM orders WHERE o_orderpriority = '1-URGENT'", 4),
            ("SELECT count(*) FROM customer WHERE c_acctbal > 5000", 2),
        ]
        with conn.cursor() as cur:
            for q, times in seeds:
                for _ in range(times):
                    cur.execute(q)
                    cur.fetchall()

        reports = analyze_workload(conn, n=10)
        print(f"Analyzed {len(reports)} slow queries:\n")
        for i, r in enumerate(reports, 1):
            s = r.slow
            print(f"  #{i}  calls={s.calls}  mean={s.mean_exec_ms:.2f}ms  "
                  f"total={s.total_exec_ms:.2f}ms")
            print(f"      {s.query}")
            if r.analysis_skipped_reason:
                print(f"      SKIPPED: {r.analysis_skipped_reason}\n")
            else:
                print(f"      → {r.plan_nodes_count} plan nodes, "
                      f"{len(r.problems)} problem(s)")
                for p in r.problems:
                    print(f"        [{p.severity.value:6s}] {p.type.value}: {p.message}")
                print()
    finally:
        conn.close()
