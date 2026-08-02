"""LLM-driven query optimizer.

Takes a query + detected problems + plan summary → asks the LLM for a
rewrite → validates that rewrite parses against Postgres → returns a
``Rewrite`` object the caller can benchmark.

The LLM only *proposes* a rewrite. Nothing hits the database beyond
``EXPLAIN`` (no ANALYZE, so no execution). Actually running the rewrite —
and comparing timings — is the caller's job via the benchmark harness.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Make cross-package imports work whether loaded as `llm.optimizer`,
# `optimizer`, or run directly. backend/ becomes the effective package root.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from analyzer.detector import Problem
from analyzer.indexes import IndexSuggestion, parse_index_statements
from analyzer.plan_parser import PlanNode
from llm.client import LLMClient, LLMResponse, get_client


SYSTEM_PROMPT = """You are a PostgreSQL query optimizer.

You will be given a SQL query, its execution plan summary, and a list of
problems detected in that plan. Suggest indexes that would help, then
return a rewritten query that takes advantage of them.

OUTPUT FORMAT — exact, no deviation:

  1. Zero or more CREATE INDEX statements, each on its own line, each
     ending with a semicolon. Emit an index only when the plan clearly
     benefits: sequential scans with selective filters, join keys with
     no index, ORDER BY on unindexed columns.
  2. A blank line.
  3. The rewritten SELECT (or WITH ... SELECT). Exactly one statement,
     no trailing semicolon required.

No markdown fences. No prose. No inline comments. Nothing else.

Hard rules — violating any of these is a failed response:
1. Every CREATE INDEX must be one of these two shapes:
     a) CREATE INDEX ON table (col1, col2, ...);
     b) CREATE INDEX ON table (col) WHERE predicate;   -- partial index
   No expression indexes, no CONCURRENTLY. The optimizer will rename
   each index to its own tmp name.
2. Do NOT emit any other DDL — no ALTER TABLE, no DROP, no ANALYZE, no
   TRUNCATE, no GRANT. Those statements will be rejected.
3. The rewritten SELECT MUST return the exact same result set as the
   original — same columns in the same order, same rows, same ordering
   when ORDER BY is present.
4. Do NOT invent columns, tables, or functions. Stick to what the
   original query references.
5. If neither an index nor a rewrite would help, emit zero indexes and
   return the query unchanged.

COMPOSITE INDEX RULE — mandatory:
When multiple filter conditions target columns on the *same* table,
emit ONE composite index that covers all of them, not several
single-column indexes.

  * Column order: equality predicates (=) FIRST, range predicates
    (>, <, >=, <=, BETWEEN) LAST. LIKE 'prefix%' counts as a range.
  * NEVER emit two separate single-column indexes on one table when a
    single composite could serve both queries.
  * If one of the equality predicates has extremely high selectivity
    (one specific value, few distinct values in the column), prefer a
    partial index instead:
        CREATE INDEX ON orders (o_totalprice) WHERE o_orderstatus = 'F';

Examples:

  WHERE status = 'F' AND price > 150000
    → CREATE INDEX ON orders (status, price);
      -- equality first, range last

  WHERE customer_id = 12 AND created_at BETWEEN a AND b
    → CREATE INDEX ON events (customer_id, created_at);

  WHERE status = 'F'   (very few distinct statuses)
    AND price > 150000
    → CREATE INDEX ON orders (price) WHERE status = 'F';
      -- partial index — smaller, faster than a composite here

STALE STATISTICS:
If the DETECTED PROBLEMS list contains a STALE_STATISTICS entry, prepend
a one-line comment to your output BEFORE the CREATE INDEX statements:

  -- Run this first: ANALYZE <table_name>;

The comment is informational — the optimizer will surface it to the
user but not execute it. Still list any indexes and the rewrite as
usual after the blank line.

Rewrite techniques you may use: reorder joins, push predicates down,
replace correlated subqueries with joins (or vice versa), lift constant
subqueries to CTEs, replace SELECT DISTINCT with GROUP BY when
equivalent, use EXISTS instead of IN for uncorrelated subqueries.

Example output:

CREATE INDEX ON events (session_id, created_at);
CREATE INDEX ON sessions (user_id);

SELECT e.id, s.started_at
FROM events e
JOIN sessions s ON s.user_id = e.user_id
WHERE e.created_at > now() - interval '7 days'
"""


@dataclass
class Rewrite:
    """Everything the optimizer produced for one query."""

    original_sql: str
    rewritten_sql: str
    llm_response: LLMResponse
    valid: bool
    validation_error: Optional[str] = None
    unchanged: bool = False  # True if the LLM returned the original verbatim
    # CREATE INDEX statements the LLM proposed, already parsed + renamed
    # to safe tmp names. The caller applies them before benchmarking the
    # rewrite and drops them after.
    index_suggestions: list[IndexSuggestion] = field(default_factory=list)
    # LLM statements we rejected (didn't match CREATE INDEX shape).
    # Surfaced for debugging bad model output; not applied.
    rejected_ddl: list[str] = field(default_factory=list)


def optimize_query(
    query: str,
    problems: list[Problem],
    plan_nodes: list[PlanNode],
    conn: Any,
    client: Optional[LLMClient] = None,
) -> Rewrite:
    """Prompt the LLM for a rewrite, then validate it against Postgres.

    Validation uses ``EXPLAIN`` (without ANALYZE) so nothing executes.
    That catches syntax errors, undefined columns, and type mismatches
    cheaply — before the caller wastes benchmark time on a bad rewrite.

    Args:
        query:      Original SQL.
        problems:   Detector output (used to steer the prompt).
        plan_nodes: Parsed plan (used to build a compact summary).
        conn:       Open psycopg2 connection (for validation).
        client:     LLM client. Defaults to ``get_client()`` (which honours
                    the ``LLM_PROVIDER`` env, falling back to Groq).

    Returns:
        A ``Rewrite`` with the LLM output and whether it parsed.
    """
    if client is None:
        client = get_client()

    user_prompt = _build_user_prompt(query, problems, plan_nodes)
    resp = client.complete(SYSTEM_PROMPT, user_prompt)
    raw = _strip_fences(resp.content).strip()

    # The model is instructed to emit CREATE INDEX statements (if any)
    # followed by the rewritten SELECT. Split them apart so we can
    # validate + apply the two halves independently.
    ddl_text, rewritten = _split_indexes_and_query(raw)
    idx_report = parse_index_statements(ddl_text)

    unchanged = _normalize(rewritten) == _normalize(query)
    valid, err = _validate_sql(rewritten, conn)

    return Rewrite(
        original_sql=query,
        rewritten_sql=rewritten,
        llm_response=resp,
        valid=valid,
        validation_error=err,
        unchanged=unchanged,
        index_suggestions=idx_report.suggestions,
        rejected_ddl=idx_report.parse_errors,
    )


def _split_indexes_and_query(text: str) -> tuple[str, str]:
    """Peel CREATE INDEX statements off the top; everything else is the query.

    The prompt asks for indexes first + a blank line + the SELECT, but
    LLMs sometimes reorder or intersperse. Robust rule: any line that,
    after stripping whitespace, starts with ``CREATE`` (case-insensitive)
    is DDL until its terminating ``;``. Everything else is the query.
    """
    ddl_stmts: list[str] = []
    query_lines: list[str] = []
    buf: list[str] = []
    in_ddl = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_ddl and stripped.upper().startswith("CREATE"):
            in_ddl = True
            buf = [line]
            if stripped.endswith(";"):
                ddl_stmts.append(" ".join(buf).strip())
                buf = []
                in_ddl = False
            continue
        if in_ddl:
            buf.append(line)
            if stripped.endswith(";"):
                ddl_stmts.append(" ".join(buf).strip())
                buf = []
                in_ddl = False
            continue
        query_lines.append(line)
    # Anything left in buf is a DDL statement missing its semicolon —
    # keep it so the parser can reject it visibly.
    if buf:
        ddl_stmts.append(" ".join(buf).strip())
    return ("\n".join(ddl_stmts), "\n".join(query_lines).strip())


def _build_user_prompt(
    query: str,
    problems: list[Problem],
    plan_nodes: list[PlanNode],
) -> str:
    """Assemble the user message: query + problems + terse plan summary."""
    if problems:
        problem_lines = "\n".join(
            f"- [{p.severity.value}] {p.type.value}: {p.message}" for p in problems
        )
    else:
        problem_lines = "(none detected)"

    plan_lines = "\n".join(
        _format_plan_line(n) for n in plan_nodes
    )

    return (
        "ORIGINAL QUERY:\n"
        f"{query.strip()}\n\n"
        "DETECTED PROBLEMS:\n"
        f"{problem_lines}\n\n"
        "PLAN SUMMARY (depth-indented):\n"
        f"{plan_lines}\n\n"
        "Return the rewritten SQL now. Only SQL, nothing else."
    )


def _format_plan_line(n: PlanNode) -> str:
    """One-line summary of a plan node for the prompt."""
    indent = "  " * n.depth
    rel = f" on {n.relation_name}" if n.relation_name else ""
    filt = f"  filter={n.filter}" if n.filter else ""
    return (
        f"{indent}- {n.node_type}{rel}  "
        f"cost={n.total_cost:.0f}  "
        f"rows(plan={n.plan_rows}, actual={n.actual_rows}, loops={n.actual_loops})"
        f"{filt}"
    )


def _strip_fences(text: str) -> str:
    """Remove ``` or ```sql fences if the LLM added them despite the rule."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    # Drop opening fence line (```sql, ```postgresql, plain ```).
    lines = lines[1:]
    # Drop closing fence if present.
    while lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _normalize(sql: str) -> str:
    """Whitespace-collapse for "did the LLM return the original verbatim" check."""
    return " ".join(sql.split()).strip().rstrip(";").lower()


def _validate_sql(sql: str, conn: Any) -> tuple[bool, Optional[str]]:
    """Run ``EXPLAIN`` (no ANALYZE) to confirm the SQL parses and plans.

    Returns (True, None) if Postgres accepts it, (False, error_message)
    if not. Rolls back so a bad statement doesn't poison the transaction.
    """
    if not sql:
        return False, "empty rewrite"
    try:
        with conn.cursor() as cur:
            cur.execute(f"EXPLAIN {sql}")
            cur.fetchall()
        return True, None
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"{type(exc).__name__}: {exc}"


# -----------------------------------------------------------------------------
# Smoke test — build a prompt and call the LLM against a real analyzed query.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import sys
    import psycopg2

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from analyzer.plan_parser import parse_plan, run_explain
    from analyzer.detector import detect_problems

    conn = psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "optimus"),
        password=os.getenv("PG_PASSWORD", "optimus"),
        dbname=os.getenv("PG_DB", "tpch"),
    )
    try:
        # A query with a clear anti-pattern: correlated subquery inside SELECT.
        query = (
            "SELECT o_orderkey, o_totalprice, "
            "(SELECT c_name FROM customer WHERE c_custkey = o_custkey) AS customer "
            "FROM orders WHERE o_orderdate = DATE '1996-01-02'"
        )
        raw = run_explain(query, conn)
        nodes = parse_plan(raw)
        problems = detect_problems(nodes)

        rewrite = optimize_query(query, problems, nodes, conn)
        print(f"LLM latency: {rewrite.llm_response.latency_ms:.0f}ms  "
              f"tokens: {rewrite.llm_response.input_tokens}→"
              f"{rewrite.llm_response.output_tokens}")
        print(f"Valid: {rewrite.valid}   Unchanged: {rewrite.unchanged}")
        if rewrite.validation_error:
            print(f"Validation error: {rewrite.validation_error}")
        print("\nORIGINAL:")
        print(rewrite.original_sql)
        print("\nREWRITE:")
        print(rewrite.rewritten_sql)
    finally:
        conn.close()
