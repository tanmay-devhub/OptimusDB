"""Phase 10.2 smoke test - hypothesize_indexes shifts the planner.

End-to-end check that:
  1. parse_index_statements  produces an IndexSuggestion from a CREATE INDEX
  2. hypothesize_indexes     registers it with HypoPG (hypopg_oid set)
  3. EXPLAIN picks up the hypothetical index (total_cost drops,
     Seq Scan -> Index Scan)
  4. reset_hypothetical      clears every hypothetical index and the plan
     reverts to the un-indexed shape

We deliberately target a table with NO permanent non-PK indexes so the
before/after shift is unambiguous. The test asserts on plan-node type
rather than absolute cost - cost numbers wiggle with stats but the plan
node type is a hard signal.

Exit 0 on success, 1 on any check failure.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from analyzer.indexes import (
    hypothesize_indexes,
    parse_index_statements,
    reset_hypothetical,
)
from analyzer.plan_parser import parse_plan, run_explain_planner_only


# A highly-selective equality lookup on orders.o_custkey - a 1.5M row
# table with no non-PK index. Without a hypothetical index the planner
# has no choice but Seq Scan; with one, it should switch to Index Scan.
# Chose orders (not orders) because orders is small enough that
# Seq Scan can beat an index even when one exists - a wall of noise
# that would make this test flaky.
DEMO_QUERY = "SELECT o_orderkey FROM orders WHERE o_custkey = 12345"
DEMO_INDEX = "CREATE INDEX ON orders (o_custkey)"


def _connect() -> psycopg2.extensions.connection:
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


def _orders_scan_node(conn) -> tuple[str, float]:
    """Return (node_type, total_cost) of the first node touching orders.

    Uses planner-only EXPLAIN: hypothetical indexes are invisible to
    EXPLAIN ANALYZE (which actually runs the query and cannot use a
    non-physical index), so ANALYZE would report the fallback Seq Scan
    even when the hypothetical index is registered.
    """
    raw = run_explain_planner_only(DEMO_QUERY, conn)
    for n in parse_plan(raw):
        if n.relation_name == "orders":
            return n.node_type, n.total_cost
    # Fallback - root node if we somehow didn't see a orders scan.
    root = parse_plan(raw)[0]
    return root.node_type, root.total_cost


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    conn = _connect()
    # Mirror how the FastAPI pool hands out connections (see api/db.py):
    # autocommit=True so run_explain does not leave a transaction open
    # that would block hypothesize_indexes' autocommit toggle.
    conn.autocommit = True
    failures: list[str] = []
    try:
        _hr("Phase 10.2 - hypothesize_indexes / reset_hypothetical")

        # 1. Parse the CREATE INDEX through the allowlist
        report = parse_index_statements(DEMO_INDEX)
        if report.parse_errors or len(report.suggestions) != 1:
            failures.append(
                f"parse_index_statements: errors={report.parse_errors} "
                f"suggestions={len(report.suggestions)}"
            )
            print(f"  [FAIL] parse_index_statements produced unexpected output")
            return 1
        sug = report.suggestions[0]
        print(f"  [OK]   parsed suggestion: {sug.ddl}")

        # 2. Baseline plan (no hypothetical yet)
        reset_hypothetical(conn)  # clean slate
        before_type, before_cost = _orders_scan_node(conn)
        print(f"  [--]   baseline node={before_type!r} cost={before_cost:.1f}")

        # 3. Register hypothetical index
        hypothesize_indexes(conn, [sug])
        if sug.error:
            failures.append(f"hypothesize_indexes error: {sug.error}")
            print(f"  [FAIL] hypothesize_indexes error: {sug.error}")
            return 1
        if not sug.applied or sug.hypopg_oid is None:
            failures.append("hypothesize_indexes did not set applied/hypopg_oid")
            print(f"  [FAIL] applied={sug.applied} hypopg_oid={sug.hypopg_oid}")
            return 1
        print(f"  [OK]   hypothesize_indexes: oid={sug.hypopg_oid}, applied=True")

        # 4. Plan shifts to an index-using node
        after_type, after_cost = _orders_scan_node(conn)
        print(f"  [--]   post-hypothesize node={after_type!r} cost={after_cost:.1f}")
        if "Index" not in after_type and "Bitmap" not in after_type:
            failures.append(
                f"planner did not adopt hypothetical index "
                f"(node still {after_type!r})"
            )
            print(f"  [FAIL] planner did not adopt hypothetical index")
        else:
            print(f"  [OK]   planner adopted hypothetical index ({after_type})")
        if after_cost >= before_cost:
            # Not a hard failure - a small query on tiny orders might
            # come out neutral. Warn but do not fail.
            print(f"  [WARN] cost did not drop ({before_cost:.1f} -> {after_cost:.1f})")

        # 5. Reset and confirm the plan reverts
        reset_hypothetical(conn)
        reset_type, reset_cost = _orders_scan_node(conn)
        print(f"  [--]   post-reset node={reset_type!r} cost={reset_cost:.1f}")
        if reset_type != before_type:
            failures.append(
                f"reset_hypothetical did not revert plan "
                f"(before={before_type!r} after-reset={reset_type!r})"
            )
            print(f"  [FAIL] reset_hypothetical did not revert plan")
        else:
            print(f"  [OK]   reset_hypothetical reverted plan to {reset_type}")

        # 6. Session-scoped: hypopg_list_indexes should be empty
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM hypopg()")
            remaining = cur.fetchone()[0]
            if remaining != 0:
                failures.append(f"hypopg_list_indexes still has {remaining} row(s)")
                print(f"  [FAIL] {remaining} hypothetical index(es) remain after reset")
            else:
                print(f"  [OK]   hypopg() is empty after reset")

        _hr("Phase 10.2 report")
        if failures:
            print(f"  FAILED ({len(failures)} check(s)):")
            for f in failures:
                print(f"    - {f}")
            return 1
        print("  PASSED - hypothetical index shifts the planner and cleans up.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
