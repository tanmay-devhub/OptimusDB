"""Plan parser.

Runs `EXPLAIN (ANALYZE, FORMAT JSON)` and flattens Postgres's nested plan
tree into a normalized `list[PlanNode]`. Downstream code — the problem
detector, the benchmark harness, the FastAPI layer — should only ever
touch PlanNode. That way, if Postgres changes its plan JSON format (it
has, historically), this module is the one place that has to adapt.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class PlanNode:
    """A single flattened node from a Postgres execution plan."""

    node_type: str
    relation_name: Optional[str]
    startup_cost: float
    total_cost: float
    plan_rows: int
    actual_rows: int
    actual_loops: int
    filter: Optional[str]
    # depth is 0 at the root and increases with nesting. It's not part of
    # the Postgres JSON — we compute it during the walk so pretty-printers
    # and the detector can reason about position without re-walking.
    depth: int


def run_explain(query: str, conn: Any, statement_timeout_ms: int = 8000) -> dict:
    """Run ``EXPLAIN (ANALYZE, FORMAT JSON)`` and return the top-level plan dict.

    A per-statement timeout is applied so a pathological query (missing
    join conditions producing a cartesian product, a stale-stats plan
    that chose nested loops over billions of rows, etc.) can't hang the
    request forever. The cross-join pre-flight in ``detect_cross_join_risk``
    is the primary defense; this is belt-and-braces.

    The returned dict contains keys like ``"Plan"``, ``"Planning Time"``,
    ``"Execution Time"``. Because ANALYZE physically executes the query,
    do not call this on mutating statements outside a transaction you
    intend to roll back.

    Args:
        query: SQL SELECT statement (any read query).
        conn:  An open psycopg2 connection.
        statement_timeout_ms: Postgres statement_timeout applied for this
            EXPLAIN only, reset immediately after. Default 8s.

    Returns:
        A dict with the plan and timing metadata.
    """
    with conn.cursor() as cur:
        # SET LOCAL would need a transaction; a plain SET + RESET in a
        # try/finally is simpler and works whether or not autocommit is on.
        cur.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
        try:
            cur.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {query}")
            row = cur.fetchone()
        finally:
            try:
                cur.execute("RESET statement_timeout")
            except Exception:
                # If the connection is in a poisoned state after a timeout,
                # roll back so subsequent statements can run.
                try:
                    conn.rollback()
                except Exception:
                    pass

    # psycopg2 usually auto-parses JSON columns; occasionally (older drivers,
    # certain type registrations) it hands back the raw string. Handle both.
    raw = row[0]
    if isinstance(raw, str):
        raw = json.loads(raw)

    # EXPLAIN JSON always wraps its result in a single-element list.
    return raw[0]


# ---------------------------------------------------------------------------
# Cross-join pre-flight
# ---------------------------------------------------------------------------
# Comma-separated FROM with fewer WHERE join conditions than tables-1 will
# produce a cartesian product. On TPC-H-shaped tables (millions of rows) this
# means EXPLAIN ANALYZE never returns. Catch it before Postgres is asked to
# plan or execute anything.

# Match FROM ... up to the first WHERE / GROUP / ORDER / LIMIT / HAVING /
# UNION / JOIN keyword (or end of string). ``JOIN`` in the stop-set means we
# only look at the pre-JOIN clause — modern JOIN syntax carries its own ON
# and is not a cross-join risk.
_FROM_RE = re.compile(
    r"\bFROM\b\s+(.+?)(?=\bWHERE\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bHAVING\b|\bUNION\b|\bJOIN\b|$)",
    re.IGNORECASE | re.DOTALL,
)
# alias.col = alias.col patterns anywhere in the query.
_JOIN_COND_RE = re.compile(r"\b(\w+)\.\w+\s*=\s*(\w+)\.\w+")


def detect_cross_join_risk(query: str) -> tuple[bool, str]:
    """Heuristic: comma-separated FROM with insufficient join predicates.

    Returns ``(True, reason)`` if a cartesian product looks likely,
    ``(False, "")`` otherwise. The heuristic is deliberately narrow so
    it doesn't false-positive on modern JOIN syntax:

    * Strips ``'literal'`` strings and ``--`` line comments before matching.
    * Only considers the FROM clause up to the first WHERE/GROUP/JOIN/etc.
    * Splits on top-level commas (no nested-paren handling for MVP).
    * Counts ``alias.col = other.col`` patterns where the two aliases
      differ. Requires at least ``tables - 1`` such conditions.

    Known limitations: does not detect risk inside subqueries, does not
    handle parenthesised join lists, does not verify aliases match
    tables. Wrong-but-safe direction — over-blocks, under-blocks rarely.
    """
    if not query or not query.strip():
        return False, ""
    q = re.sub(r"'[^']*'", "''", query)
    q = re.sub(r"--[^\n]*", "", q)

    m = _FROM_RE.search(q)
    if not m:
        return False, ""
    tables = [t.strip() for t in m.group(1).split(",") if t.strip()]
    if len(tables) < 2:
        return False, ""

    join_pairs = _JOIN_COND_RE.findall(q)
    real_joins = sum(1 for a, b in join_pairs if a.lower() != b.lower())

    needed = len(tables) - 1
    if real_joins < needed:
        return True, (
            f"FROM clause lists {len(tables)} tables but only "
            f"{real_joins} join predicate{'s' if real_joins != 1 else ''} — "
            f"expected at least {needed}. This would produce a cartesian "
            f"product. Add explicit JOIN conditions before analyzing."
        )
    return False, ""


def parse_plan(plan_json: dict) -> list[PlanNode]:
    """Walk a plan tree and return a depth-first, pre-order flat list.

    Accepts either the full ``run_explain`` output (dict with a ``"Plan"``
    key) or a bare plan subtree.

    Args:
        plan_json: The dict returned by ``run_explain``.

    Returns:
        Flat list of ``PlanNode`` in root-first, pre-order traversal.
    """
    nodes: list[PlanNode] = []
    root = plan_json["Plan"] if "Plan" in plan_json else plan_json
    _walk(root, depth=0, out=nodes)
    return nodes


def _walk(node: dict, depth: int, out: list[PlanNode]) -> None:
    """Append ``node`` to ``out`` then recurse into its ``Plans`` children."""
    out.append(
        PlanNode(
            node_type=node["Node Type"],
            relation_name=node.get("Relation Name"),
            startup_cost=float(node.get("Startup Cost", 0.0)),
            total_cost=float(node.get("Total Cost", 0.0)),
            plan_rows=int(node.get("Plan Rows", 0)),
            actual_rows=int(node.get("Actual Rows", 0)),
            actual_loops=int(node.get("Actual Loops", 1)),
            filter=node.get("Filter"),
            depth=depth,
        )
    )
    for child in node.get("Plans", []):
        _walk(child, depth + 1, out)


# -----------------------------------------------------------------------------
# Smoke test — run `python plan_parser.py` against the Docker Postgres.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import psycopg2

    conn = psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "optimus"),
        password=os.getenv("PG_PASSWORD", "optimus"),
        dbname=os.getenv("PG_DB", "tpch"),
    )
    try:
        # A deliberately un-indexed filter — this is what Phase 1 is built to spot.
        raw = run_explain(
            "SELECT c_mktsegment, count(*) FROM customer "
            "WHERE c_acctbal > 5000 GROUP BY c_mktsegment",
            conn,
        )
        nodes = parse_plan(raw)
        print(f"Parsed {len(nodes)} plan nodes "
              f"(planning={raw['Planning Time']:.2f}ms, "
              f"execution={raw['Execution Time']:.2f}ms):\n")
        for n in nodes:
            indent = "  " * n.depth
            rel = f" on {n.relation_name}" if n.relation_name else ""
            filt = f"  filter={n.filter!r}" if n.filter else ""
            print(
                f"{indent}- {n.node_type}{rel}  "
                f"cost={n.startup_cost:.1f}..{n.total_cost:.1f}  "
                f"rows(plan={n.plan_rows}, actual={n.actual_rows}, loops={n.actual_loops})"
                f"{filt}"
            )
    finally:
        conn.close()
