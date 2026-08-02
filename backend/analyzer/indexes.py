"""Parse, apply, and drop LLM-suggested indexes.

This is the *only* module in the backend that mutates the schema. Every
statement is validated against a strict allowlist (CREATE INDEX only —
no ALTER, no DROP TABLE, no anything else) and renamed to a
``optimusdb_tmp_<uuid>`` prefix so we can never accidentally drop an
index the user owns during cleanup.

The caller is expected to wrap ``apply_indexes`` / ``drop_indexes`` in
try/finally so cleanup happens even when a benchmark blows up. If the
process is killed between CREATE and DROP the temporary indexes will
leak — the naming prefix makes them easy to find and drop manually:

    SELECT indexname FROM pg_indexes WHERE indexname LIKE 'optimusdb_tmp_%';
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


_TMP_PREFIX = "optimusdb_tmp_"

# Enforce a very tight shape: CREATE [UNIQUE] INDEX [IF NOT EXISTS]
# [name] ON [schema.]table [USING method] (col_list) [WHERE predicate].
# We *replace* the LLM's chosen name with our own tmp name, so the name
# group can be anything the LLM emitted — we throw it away.
#
# Partial indexes are allowed because the composite-vs-partial rule in
# SYSTEM_PROMPT can produce them; the WHERE predicate is limited to
# characters that cannot introduce another statement or subquery.
_CREATE_INDEX_RE = re.compile(
    r"""
    ^\s*CREATE\s+
    (?:UNIQUE\s+)?
    INDEX\s+
    (?:CONCURRENTLY\s+)?
    (?:IF\s+NOT\s+EXISTS\s+)?
    (?:(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\s+)?
    ON\s+
    (?P<table>(?:[a-zA-Z_][a-zA-Z0-9_]*\.)?[a-zA-Z_][a-zA-Z0-9_]*)
    (?:\s+USING\s+[a-zA-Z_]+)?
    \s*\(
    (?P<cols>[^()]+)
    \)
    (?:\s+WHERE\s+(?P<where>[^;()]+?))?
    \s*;?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# WHERE predicate must not smuggle DDL/DML. Character class already blocks
# semicolons and parens; this catches keyword-based abuse.
_UNSAFE_IN_WHERE = re.compile(
    r"\b(alter|drop|truncate|grant|revoke|insert|update|delete|create|copy|call|do|execute)\b",
    re.IGNORECASE,
)


@dataclass
class IndexSuggestion:
    """A CREATE INDEX statement, rewritten with our tmp name."""

    tmp_name: str          # our safe generated name (starts with optimusdb_tmp_)
    original_name: Optional[str]  # what the LLM called it (informational)
    table: str
    columns: str           # raw column list as written (e.g. "col1, col2 DESC")
    where: Optional[str]   # partial-index predicate, or None for a full index
    ddl: str               # the final CREATE INDEX we will execute
    applied: bool = False
    error: Optional[str] = None


@dataclass
class IndexApplyReport:
    """Everything the caller needs to know about what we did."""

    suggestions: list[IndexSuggestion] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)  # statements we rejected


def _new_tmp_name() -> str:
    # 8 hex chars is plenty of entropy for de-duping within one request;
    # postgres identifier limit is 63 chars, well under.
    return f"{_TMP_PREFIX}{uuid.uuid4().hex[:8]}"


def _split_statements(text: str) -> list[str]:
    """Split a blob into individual statements on top-level ``;``.

    Naive but sufficient for CREATE INDEX — those never contain string
    literals or nested statements. Comments (``--`` line comments) are
    stripped first so a semicolon in a comment can't split.
    """
    # Strip -- line comments
    cleaned = re.sub(r"--[^\n]*", "", text)
    parts = [p.strip() for p in cleaned.split(";")]
    return [p for p in parts if p]


def parse_index_statements(text: str) -> IndexApplyReport:
    """Extract CREATE INDEX statements from LLM output.

    Any statement that doesn't match the strict CREATE INDEX shape is
    rejected and reported as a parse error — that includes ALTER TABLE,
    DROP anything, TRUNCATE, GRANT, and every other DDL/DML we don't
    want the LLM smuggling in.
    """
    report = IndexApplyReport()
    for stmt in _split_statements(text):
        m = _CREATE_INDEX_RE.match(stmt)
        if not m:
            report.parse_errors.append(stmt[:200])
            continue
        original_name = m.group("name")
        table = m.group("table")
        cols = m.group("cols").strip()
        where = m.group("where")
        if where is not None:
            where = where.strip()
            if _UNSAFE_IN_WHERE.search(where):
                # WHERE clause contains DDL/DML keywords — reject outright.
                report.parse_errors.append(stmt[:200])
                continue
        tmp_name = _new_tmp_name()
        # Reconstruct with our safe name so the LLM can't collide with a
        # real index the user owns. Default access method (btree). Partial
        # index WHERE predicate is preserved when present.
        ddl = f'CREATE INDEX {tmp_name} ON {table} ({cols})'
        if where:
            ddl = f'{ddl} WHERE {where}'
        report.suggestions.append(
            IndexSuggestion(
                tmp_name=tmp_name,
                original_name=original_name,
                table=table,
                columns=cols,
                where=where,
                ddl=ddl,
            )
        )
    return report


def apply_indexes(
    conn: Any,
    suggestions: list[IndexSuggestion],
    statement_timeout_ms: int = 60_000,
) -> None:
    """Execute each suggestion's DDL. Sets a statement_timeout so a
    pathological CREATE INDEX (huge table, no free disk) can't hang the
    request forever. Autocommit is toggled on so CREATE INDEX doesn't
    hold a transaction open across the subsequent benchmark.

    Failures are recorded on the individual IndexSuggestion — we do not
    raise — so partial success is possible and the caller can still
    benchmark whatever indexes did land. The caller MUST call
    ``drop_indexes`` regardless.
    """
    prev_autocommit = getattr(conn, "autocommit", False)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
            for s in suggestions:
                try:
                    cur.execute(s.ddl)
                    s.applied = True
                except Exception as exc:
                    s.applied = False
                    s.error = f"{type(exc).__name__}: {exc}"
            # Reset so subsequent benchmark isn't clipped.
            cur.execute("RESET statement_timeout")
    finally:
        conn.autocommit = prev_autocommit


def drop_indexes(conn: Any, suggestions: list[IndexSuggestion]) -> list[str]:
    """Drop every index we applied. Best-effort — logs failures instead
    of raising so cleanup can continue past a single bad DROP.

    Returns the list of tmp_names we failed to drop, if any. Empty list
    means the database is back to the exact state it was in before.
    """
    failed: list[str] = []
    prev_autocommit = getattr(conn, "autocommit", False)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for s in suggestions:
                if not s.applied:
                    continue
                # IF EXISTS so a partial-failure state doesn't cascade.
                # Extra belt-and-braces: we generated the name, so this
                # can only target something we created.
                try:
                    cur.execute(f'DROP INDEX IF EXISTS "{s.tmp_name}"')
                except Exception:
                    failed.append(s.tmp_name)
    finally:
        conn.autocommit = prev_autocommit
    return failed
