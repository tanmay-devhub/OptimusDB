"""Pydantic request/response schemas for the HTTP layer.

These mirror the internal dataclasses (PlanNode, Problem, BenchmarkResult,
SlowQuery, Rewrite) but are the *only* types that cross the network. If
we ever change an internal dataclass, we choose then whether to reflect
the change in the API — the wire format stays under our control.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# Two operating modes for /optimize.
#   "measure"      - apply/bench/drop real indexes, report wall-clock speedup
#   "hypothetical" - register HypoPG indexes, report planner cost_ratio
# Default stays "measure" for backward compatibility with existing callers.
OptimizeMode = Literal["measure", "hypothetical"]


# --- Requests ---------------------------------------------------------------

class QueryRequest(BaseModel):
    """Any endpoint that takes a single SQL query."""

    query: str = Field(..., min_length=1, description="Read-only SQL to analyze.")
    # Only consulted by /optimize. /analyze ignores it. Default is
    # "measure" so existing clients keep the current apply/bench/drop
    # behavior. "hypothetical" is the production-safe path - HypoPG
    # only, no benchmarks, no physical DDL.
    mode: OptimizeMode = Field(
        default="measure",
        description=(
            "Optimization mode. 'measure' applies real indexes and benchmarks "
            "both queries (accurate, slow, unsafe on huge tables). "
            "'hypothetical' uses HypoPG and compares planner costs "
            "(fast, safe, planner-cost currency instead of wall-clock)."
        ),
    )


class BenchmarkRequest(BaseModel):
    """POST /benchmark — measure one query, N runs."""

    query: str = Field(..., min_length=1)
    n: int = Field(default=10, ge=4, le=100, description="Total runs. Min 4.")


class WorkloadRequest(BaseModel):
    """GET-style options for /workload passed as JSON body for simplicity."""

    n: int = Field(default=10, ge=1, le=100)
    min_calls: int = Field(default=1, ge=1)


# --- Response fragments -----------------------------------------------------

class PlanNodeOut(BaseModel):
    node_type: str
    relation_name: Optional[str] = None
    startup_cost: float
    total_cost: float
    plan_rows: int
    actual_rows: int
    actual_loops: int
    filter: Optional[str] = None
    depth: int


class ProblemOut(BaseModel):
    type: str
    severity: str
    message: str
    node_type: str
    relation_name: Optional[str] = None


class BenchmarkOut(BaseModel):
    n: int
    cold_ms: float
    warm_p50_ms: float
    warm_p95_ms: float
    warm_min_ms: float
    warm_max_ms: float
    all_runs_ms: list[float]


class LLMResponseOut(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class IndexOut(BaseModel):
    """One LLM-suggested index, after we renamed it to our tmp name."""

    tmp_name: str
    original_name: Optional[str] = None
    table: str
    columns: str
    ddl: str
    applied: bool
    error: Optional[str] = None
    # Set only when the index was registered as a HypoPG hypothetical
    # (i.e. mode="hypothetical"). None for the physical-apply path.
    hypopg_oid: Optional[int] = None


class PlanChangeOut(BaseModel):
    """How the plan for one relation shifted after applying indexes."""

    relation: str
    before_node_type: str
    after_node_type: str
    changed: bool


class SlowQueryOut(BaseModel):
    queryid: int
    query: str
    calls: int
    total_exec_ms: float
    mean_exec_ms: float
    stddev_exec_ms: float
    rows: int


# --- Response envelopes -----------------------------------------------------

class AnalyzeResponse(BaseModel):
    """POST /analyze — deterministic analysis, no LLM."""

    query: str
    plan_nodes: list[PlanNodeOut]
    problems: list[ProblemOut]
    planning_ms: float
    execution_ms: float
    # Non-empty when a pre-flight guard (currently: cross-join detector)
    # blocked EXPLAIN from running. plan_nodes will be empty; problems
    # will contain a single explanatory Problem row.
    blocked_reason: Optional[str] = None


class OptimizeResponse(BaseModel):
    """POST /optimize — analyze + LLM rewrite + apply indexes + benchmark both."""

    original_sql: str
    rewritten_sql: str
    valid: bool
    unchanged: bool
    validation_error: Optional[str] = None
    # Optional so pre-flight blocks (cross-join risk) can return without
    # burning tokens. Present on every non-blocked response.
    llm: Optional[LLMResponseOut] = None
    # Non-empty when the pre-flight guard short-circuited before any DB
    # work. UI surfaces this as a red banner over the diff pane.
    blocked_reason: Optional[str] = None
    # Which pipeline ran. Echoed back so the frontend can label the
    # verdict correctly ("Measured 47.4x faster" vs "Planner estimates
    # 47.4x cheaper").
    mode: OptimizeMode = "measure"
    original_benchmark: Optional[BenchmarkOut] = None
    rewrite_benchmark: Optional[BenchmarkOut] = None
    speedup: Optional[float] = Field(
        default=None,
        description="warm_p50(original) / warm_p50(rewrite). >1 means rewrite is faster. Only set in mode='measure'.",
    )
    # Planner cost ratio: total_cost(original) / total_cost(rewrite).
    # >1 means the planner thinks the rewrite is cheaper. Only set in
    # mode='hypothetical'; speedup will be None in that mode.
    cost_ratio: Optional[float] = Field(
        default=None,
        description="total_cost(original) / total_cost(rewrite_with_hypothetical_indexes). >1 means planner prefers the rewrite. Only set in mode='hypothetical'.",
    )
    original_total_cost: Optional[float] = Field(
        default=None,
        description="Planner total_cost for the original query. Set in both modes.",
    )
    rewrite_total_cost: Optional[float] = Field(
        default=None,
        description="Planner total_cost for the rewrite (with hypothetical indexes in hypothetical mode).",
    )
    problems: list[ProblemOut]
    # Indexes the LLM proposed. Each carries whether we successfully
    # applied it and (if not) why. All are dropped again before this
    # response is returned — the DB is back to its starting state.
    applied_indexes: list[IndexOut] = Field(default_factory=list)
    # Any non-CREATE-INDEX statements the LLM tried to smuggle in. Not
    # executed. Surfaced here so a broken prompt is debuggable.
    rejected_ddl: list[str] = Field(default_factory=list)
    # For each relation touched: node type before indexes vs after.
    # This is the concrete evidence the indexes did anything.
    plan_changes: list[PlanChangeOut] = Field(default_factory=list)
    # Names we couldn't drop on cleanup — should always be empty. If not,
    # user can drop manually: DROP INDEX <name>.
    cleanup_leaks: list[str] = Field(default_factory=list)


class BenchmarkResponse(BaseModel):
    """POST /benchmark — single-query timing."""

    query: str
    benchmark: BenchmarkOut


class WorkloadResponse(BaseModel):
    """POST /workload — top-N slow queries with per-query analysis."""

    queries: list[SlowQueryOut]
    reports: list["WorkloadReportOut"]


class WorkloadReportOut(BaseModel):
    slow: SlowQueryOut
    problems: list[ProblemOut]
    plan_nodes_count: int
    analysis_skipped_reason: Optional[str] = None


WorkloadResponse.model_rebuild()


class HealthResponse(BaseModel):
    ok: bool
    postgres: bool
    detail: Optional[str] = None
