"""Problem detector.

Deterministic heuristics over `list[PlanNode]`. No LLM here — four rules
that consistently surface issues a query planner tends to hit. Rules can
overlap (a large filtered Seq Scan will trigger both SEQ_SCAN_LARGE and
MISSING_INDEX_CANDIDATE); dedup and prioritization are for the UI layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

try:
    # Works when imported as `analyzer.detector` (normal package usage).
    from .plan_parser import PlanNode
except ImportError:  # pragma: no cover — direct-script convenience only
    from plan_parser import PlanNode


class ProblemType(str, Enum):
    """Enumerates every rule the detector can emit."""

    SEQ_SCAN_LARGE = "SEQ_SCAN_LARGE"
    ROW_ESTIMATE_ERROR = "ROW_ESTIMATE_ERROR"
    NESTED_LOOP_HIGH_ROWS = "NESTED_LOOP_HIGH_ROWS"
    MISSING_INDEX_CANDIDATE = "MISSING_INDEX_CANDIDATE"
    # Planner estimate off by 100x+ — table statistics likely stale.
    # Emitted alongside ROW_ESTIMATE_ERROR when the ratio is extreme, so
    # the user gets an actionable ANALYZE command rather than just a
    # "planner was wrong" observation.
    STALE_STATISTICS = "STALE_STATISTICS"
    # Query has fewer join predicates than tables - 1 (implicit cartesian).
    # Emitted by the pre-flight guard, never by the plan-node rules —
    # the plan for such a query would never return in the first place.
    CROSS_JOIN_RISK = "CROSS_JOIN_RISK"


class Severity(str, Enum):
    """Two-level triage — HIGH warrants immediate attention, MEDIUM is worth reviewing."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


@dataclass
class Problem:
    """One flagged issue anchored to one plan node."""

    type: ProblemType
    node: PlanNode
    severity: Severity
    message: str


# Thresholds calibrated for TPC-H SF=1. Tune later per workload.
_SEQ_SCAN_ROW_THRESHOLD = 1_000
_SEQ_SCAN_HIGH_THRESHOLD = 100_000
_ROW_EST_RATIO_HIGH = 10.0
_ROW_EST_RATIO_EGREGIOUS = 100.0
_ROW_EST_MIN_ACTUAL = 10  # skip nodes that barely produce anything (noise filter)
_NESTED_LOOP_ROW_THRESHOLD = 500
_NESTED_LOOP_HIGH_THRESHOLD = 10_000
_STALE_STATS_RATIO_THRESHOLD = 100.0  # above this, blame stats, recommend ANALYZE


def detect_problems(nodes: list[PlanNode]) -> list[Problem]:
    """Run every rule against every plan node and return the union.

    Args:
        nodes: Flat plan-node list from `parse_plan`.

    Returns:
        Detected problems in plan-node order. Empty list means no rule fired.
    """
    problems: list[Problem] = []
    for n in nodes:
        problems.extend(_check_seq_scan_large(n))
        problems.extend(_check_row_estimate_error(n))
        problems.extend(_check_nested_loop_high_rows(n))
        problems.extend(_check_missing_index_candidate(n))
        problems.extend(_check_stale_statistics(n))
    return problems


def _check_stale_statistics(node: PlanNode) -> list[Problem]:
    """Fire when planner estimate is off by 100x+ — points at ANALYZE.

    Runs on the same nodes as ROW_ESTIMATE_ERROR (which fires at 10x) but
    with a higher threshold and an actionable message. Both can fire on
    the same node; the UI treats them as distinct hints.
    """
    if node.plan_rows <= 0:
        return []
    total_actual = _total_rows(node)
    if total_actual < _ROW_EST_MIN_ACTUAL:
        return []
    hi = max(node.plan_rows, total_actual)
    lo = max(min(node.plan_rows, total_actual), 1)
    ratio = hi / lo
    if ratio < _STALE_STATS_RATIO_THRESHOLD:
        return []
    rel = node.relation_name or ""
    analyze_cmd = f"ANALYZE {rel};" if rel else "ANALYZE;"
    where = f" on {rel}" if rel else ""
    return [Problem(
        type=ProblemType.STALE_STATISTICS,
        node=node,
        severity=Severity.HIGH,
        message=(
            f"Planner estimate off by {ratio:.0f}x{where} — table "
            f"statistics are likely stale. Run: {analyze_cmd}"
        ),
    )]


def _total_rows(node: PlanNode) -> int:
    """Total rows produced by a node across all executions.

    Postgres reports `Actual Rows` as a per-loop average, so a node inside
    a nested loop with N iterations really produced actual_rows * N rows.
    """
    return node.actual_rows * max(node.actual_loops, 1)


def _check_seq_scan_large(node: PlanNode) -> list[Problem]:
    """Fire if this is a Seq Scan producing more than the row threshold."""
    if node.node_type != "Seq Scan":
        return []
    total = _total_rows(node)
    if total <= _SEQ_SCAN_ROW_THRESHOLD:
        return []
    severity = Severity.HIGH if total > _SEQ_SCAN_HIGH_THRESHOLD else Severity.MEDIUM
    rel = node.relation_name or "?"
    return [Problem(
        type=ProblemType.SEQ_SCAN_LARGE,
        node=node,
        severity=severity,
        message=f"Seq Scan on {rel} touched {total:,} rows — consider an index.",
    )]


def _check_row_estimate_error(node: PlanNode) -> list[Problem]:
    """Fire if planner's row estimate is off by 10x or more (either direction)."""
    if node.plan_rows <= 0:
        return []
    total_actual = _total_rows(node)
    if total_actual < _ROW_EST_MIN_ACTUAL:
        return []
    ratio = total_actual / node.plan_rows
    if (1.0 / _ROW_EST_RATIO_HIGH) <= ratio <= _ROW_EST_RATIO_HIGH:
        return []
    egregious = ratio >= _ROW_EST_RATIO_EGREGIOUS or ratio <= (1.0 / _ROW_EST_RATIO_EGREGIOUS)
    severity = Severity.HIGH if egregious else Severity.MEDIUM
    rel = f" on {node.relation_name}" if node.relation_name else ""
    direction = "under-estimated" if ratio > 1 else "over-estimated"
    return [Problem(
        type=ProblemType.ROW_ESTIMATE_ERROR,
        node=node,
        severity=severity,
        message=(
            f"{node.node_type}{rel}: planner {direction} rows "
            f"(expected {node.plan_rows:,}, got {total_actual:,}, ratio {ratio:.1f}x) "
            f"— stale statistics or correlated predicates."
        ),
    )]


def _check_nested_loop_high_rows(node: PlanNode) -> list[Problem]:
    """Fire if a Nested Loop is producing enough rows that hash/merge would win."""
    if node.node_type != "Nested Loop":
        return []
    total = _total_rows(node)
    if total <= _NESTED_LOOP_ROW_THRESHOLD:
        return []
    severity = Severity.HIGH if total > _NESTED_LOOP_HIGH_THRESHOLD else Severity.MEDIUM
    return [Problem(
        type=ProblemType.NESTED_LOOP_HIGH_ROWS,
        node=node,
        severity=severity,
        message=(
            f"Nested Loop produced {total:,} rows — hash or merge join is usually "
            f"faster at this scale."
        ),
    )]


def _check_missing_index_candidate(node: PlanNode) -> list[Problem]:
    """Fire if a Seq Scan carries a filter predicate on a non-trivial table."""
    if node.node_type != "Seq Scan" or not node.filter:
        return []
    total = _total_rows(node)
    # Skip small lookup tables (region, nation) — indexing them is pointless.
    if total < _SEQ_SCAN_ROW_THRESHOLD:
        return []
    severity = Severity.HIGH if total > _SEQ_SCAN_HIGH_THRESHOLD else Severity.MEDIUM
    rel = node.relation_name or "?"
    return [Problem(
        type=ProblemType.MISSING_INDEX_CANDIDATE,
        node=node,
        severity=severity,
        message=(
            f"Seq Scan on {rel} with filter {node.filter!r} — an index on the "
            f"filtered column(s) could replace the full scan."
        ),
    )]


# -----------------------------------------------------------------------------
# Smoke test — TPC-H Q3-style query hits Seq Scan + big joins with no indexes.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import sys
    import psycopg2
    from plan_parser import run_explain, parse_plan

    # Windows console defaults to cp1252 which mangles em-dashes.
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
        query = """
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
        raw = run_explain(query, conn)
        nodes = parse_plan(raw)
        problems = detect_problems(nodes)
        print(f"Parsed {len(nodes)} plan nodes, "
              f"detected {len(problems)} problem(s) "
              f"(execution={raw['Execution Time']:.1f}ms):\n")
        for p in problems:
            print(f"  [{p.severity.value:6s}] {p.type.value}")
            print(f"           {p.message}\n")
    finally:
        conn.close()
