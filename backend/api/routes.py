"""HTTP routes for the AI Query Optimizer.

Endpoints intentionally split so cost and latency are the client's choice:

- ``GET /health``            — cheap liveness probe.
- ``POST /analyze``          — deterministic parse + detect only. No LLM.
- ``POST /optimize``         — analyze + LLM rewrite + benchmark both. Slow.
- ``POST /benchmark``        — single-query benchmark. No analysis.
- ``POST /workload``         — top-N slow queries + auto-analysis of each.

Every heavy dependency (parser, detector, harness, optimizer) is imported
from the existing Phase 1-3 modules — this file only glues.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from analyzer.batch import analyze_workload
from analyzer.detector import Problem, ProblemType, Severity, detect_problems
from analyzer.indexes import apply_indexes, drop_indexes
from analyzer.plan_parser import PlanNode, detect_cross_join_risk, parse_plan, run_explain
from benchmarks.harness import BenchmarkResult, run_benchmark
from llm.optimizer import optimize_query

from .db import get_conn
from .schemas import (
    AnalyzeResponse,
    BenchmarkOut,
    BenchmarkRequest,
    BenchmarkResponse,
    HealthResponse,
    IndexOut,
    LLMResponseOut,
    OptimizeResponse,
    PlanChangeOut,
    PlanNodeOut,
    ProblemOut,
    QueryRequest,
    SlowQueryOut,
    WorkloadReportOut,
    WorkloadRequest,
    WorkloadResponse,
)


router = APIRouter()


# --- Converters (internal dataclass → wire schema) ---------------------------

def _plan_node_out(n: PlanNode) -> PlanNodeOut:
    """Copy a PlanNode into its Pydantic mirror."""
    return PlanNodeOut(
        node_type=n.node_type,
        relation_name=n.relation_name,
        startup_cost=n.startup_cost,
        total_cost=n.total_cost,
        plan_rows=n.plan_rows,
        actual_rows=n.actual_rows,
        actual_loops=n.actual_loops,
        filter=n.filter,
        depth=n.depth,
    )


def _problem_out(p: Problem) -> ProblemOut:
    """Flatten a Problem — we surface node_type/relation instead of the whole node."""
    return ProblemOut(
        type=p.type.value,
        severity=p.severity.value,
        message=p.message,
        node_type=p.node.node_type,
        relation_name=p.node.relation_name,
    )


def _bench_out(b: BenchmarkResult) -> BenchmarkOut:
    """Copy a BenchmarkResult into its Pydantic mirror."""
    return BenchmarkOut(
        n=b.n,
        cold_ms=b.cold_ms,
        warm_p50_ms=b.warm_p50_ms,
        warm_p95_ms=b.warm_p95_ms,
        warm_min_ms=b.warm_min_ms,
        warm_max_ms=b.warm_max_ms,
        all_runs_ms=b.all_runs_ms,
    )


# --- Routes ------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
def health(conn=Depends(get_conn)) -> HealthResponse:
    """Liveness: can we round-trip SELECT 1?"""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return HealthResponse(ok=True, postgres=True)
    except Exception as exc:
        return HealthResponse(ok=False, postgres=False, detail=str(exc))


def _cross_join_problem(reason: str) -> ProblemOut:
    """Synthetic Problem card for a pre-flight-blocked query.

    Not derived from a plan node (there is none), so we hand-fill the
    node_type/relation_name fields the wire schema requires.
    """
    return ProblemOut(
        type=ProblemType.CROSS_JOIN_RISK.value,
        severity=Severity.HIGH.value,
        message=reason,
        node_type="(query)",
        relation_name=None,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: QueryRequest, conn=Depends(get_conn)) -> AnalyzeResponse:
    """Parse the plan and run the deterministic problem detector. No LLM.

    Pre-flight: cross-join risk short-circuits before EXPLAIN so we never
    ask Postgres to plan a trillion-row cartesian product.
    """
    is_risk, reason = detect_cross_join_risk(req.query)
    if is_risk:
        return AnalyzeResponse(
            query=req.query,
            plan_nodes=[],
            problems=[_cross_join_problem(reason)],
            planning_ms=0.0,
            execution_ms=0.0,
            blocked_reason=reason,
        )

    try:
        raw = run_explain(req.query, conn)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"EXPLAIN failed: {exc}")
    nodes = parse_plan(raw)
    problems = detect_problems(nodes)
    return AnalyzeResponse(
        query=req.query,
        plan_nodes=[_plan_node_out(n) for n in nodes],
        problems=[_problem_out(p) for p in problems],
        planning_ms=float(raw.get("Planning Time", 0.0)),
        execution_ms=float(raw.get("Execution Time", 0.0)),
    )


def _rel_to_node_type(nodes: list[PlanNode]) -> dict[str, str]:
    """First (deepest-first traversal) node type per touched relation.

    The plan_parser returns nodes in visit order; a relation appears
    once, on its scan node. Keeping the *first* occurrence is what
    matches the user-visible "how are we hitting this table" question.
    """
    out: dict[str, str] = {}
    for n in nodes:
        if n.relation_name and n.relation_name not in out:
            out[n.relation_name] = n.node_type
    return out


def _plan_changes(before: list[PlanNode], after: list[PlanNode]) -> list[PlanChangeOut]:
    """Diff node types per relation, only emit relations that appear in
    either plan. Order matches the ``before`` plan's traversal so the
    tables the user cared about show up first."""
    a = _rel_to_node_type(before)
    b = _rel_to_node_type(after)
    changes: list[PlanChangeOut] = []
    seen: set[str] = set()
    for rel, bt in a.items():
        seen.add(rel)
        at = b.get(rel, bt)
        changes.append(PlanChangeOut(
            relation=rel,
            before_node_type=bt,
            after_node_type=at,
            changed=(at != bt),
        ))
    for rel, at in b.items():
        if rel in seen:
            continue
        changes.append(PlanChangeOut(
            relation=rel,
            before_node_type="(not scanned)",
            after_node_type=at,
            changed=True,
        ))
    return changes


@router.post("/optimize", response_model=OptimizeResponse)
def optimize(req: QueryRequest, conn=Depends(get_conn)) -> OptimizeResponse:
    """Analyze → LLM rewrite (+ index suggestions) → apply indexes →
    benchmark both → drop indexes → verdict.

    The DB is mutated (CREATE INDEX) and then restored (DROP INDEX)
    within this single request. If cleanup fails, the tmp names are
    reported in ``cleanup_leaks`` and can be dropped manually.
    """
    # Pre-flight cross-join guard — same rationale as /analyze. Short-circuit
    # before any DB work or LLM call, since a cartesian-product query would
    # never come back from EXPLAIN and the LLM has no reliable way to guess
    # the missing join conditions from arbitrary schemas.
    is_risk, reason = detect_cross_join_risk(req.query)
    if is_risk:
        return OptimizeResponse(
            original_sql=req.query,
            rewritten_sql="",
            valid=False,
            unchanged=False,
            validation_error=None,
            llm=None,
            original_benchmark=None,
            rewrite_benchmark=None,
            speedup=None,
            problems=[_cross_join_problem(reason)],
            applied_indexes=[],
            rejected_ddl=[],
            plan_changes=[],
            cleanup_leaks=[],
            blocked_reason=reason,
        )

    try:
        raw = run_explain(req.query, conn)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"EXPLAIN failed: {exc}")

    nodes_before = parse_plan(raw)
    problems = detect_problems(nodes_before)

    try:
        rewrite = optimize_query(req.query, problems, nodes_before, conn)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    orig_b: BenchmarkOut | None = None
    new_b: BenchmarkOut | None = None
    speedup: float | None = None
    plan_changes: list[PlanChangeOut] = []
    cleanup_leaks: list[str] = []

    # Bench + index-apply only makes sense if the rewrite parses. If it
    # doesn't, we bail out with what we have — no DB mutation happens.
    if rewrite.valid:
        # 1. Benchmark the ORIGINAL first — before any indexes exist —
        #    so its numbers are honest baseline. (We don't benchmark
        #    inside the try/finally because we don't want cleanup ordering
        #    weirdness with the original run.)
        orig_b = _bench_out(run_benchmark(rewrite.original_sql, conn, n=10))

        # 2. Apply indexes. try/finally guarantees drop happens even if
        #    EXPLAIN or benchmark below throws. Note: apply_indexes never
        #    raises — per-index failures are recorded on the suggestion.
        try:
            apply_indexes(conn, rewrite.index_suggestions)

            # 3. Re-EXPLAIN with the indexes in place, so plan_changes
            #    reflects the actual "after" plan. If the rewrite is
            #    unchanged we still bench it — that surfaces the pure
            #    "indexes only" benefit.
            try:
                raw_after = run_explain(rewrite.rewritten_sql, conn)
                nodes_after = parse_plan(raw_after)
                plan_changes = _plan_changes(nodes_before, nodes_after)
            except Exception:
                # Rewrite validated moments ago; a fresh EXPLAIN failure
                # here would be surprising but not fatal — skip the
                # plan-change diff and still benchmark.
                plan_changes = []

            # 4. Benchmark the rewrite with indexes in place.
            new_b = _bench_out(run_benchmark(rewrite.rewritten_sql, conn, n=10))
            if orig_b and new_b.warm_p50_ms > 0:
                speedup = orig_b.warm_p50_ms / new_b.warm_p50_ms
        finally:
            # 5. Drop everything we created, always.
            cleanup_leaks = drop_indexes(conn, rewrite.index_suggestions)

    applied_indexes = [
        IndexOut(
            tmp_name=s.tmp_name,
            original_name=s.original_name,
            table=s.table,
            columns=s.columns,
            ddl=s.ddl,
            applied=s.applied,
            error=s.error,
        )
        for s in rewrite.index_suggestions
    ]

    return OptimizeResponse(
        original_sql=rewrite.original_sql,
        rewritten_sql=rewrite.rewritten_sql,
        valid=rewrite.valid,
        unchanged=rewrite.unchanged,
        validation_error=rewrite.validation_error,
        llm=LLMResponseOut(
            model=rewrite.llm_response.model,
            input_tokens=rewrite.llm_response.input_tokens,
            output_tokens=rewrite.llm_response.output_tokens,
            latency_ms=rewrite.llm_response.latency_ms,
        ),
        original_benchmark=orig_b,
        rewrite_benchmark=new_b,
        speedup=speedup,
        problems=[_problem_out(p) for p in problems],
        applied_indexes=applied_indexes,
        rejected_ddl=rewrite.rejected_ddl,
        plan_changes=plan_changes,
        cleanup_leaks=cleanup_leaks,
    )


@router.post("/benchmark", response_model=BenchmarkResponse)
def benchmark(req: BenchmarkRequest, conn=Depends(get_conn)) -> BenchmarkResponse:
    """Benchmark a single query. Cheaper than /optimize when you already have a rewrite."""
    try:
        result = run_benchmark(req.query, conn, n=req.n)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Benchmark failed: {exc}")
    return BenchmarkResponse(query=req.query, benchmark=_bench_out(result))


@router.post("/workload", response_model=WorkloadResponse)
def workload(req: WorkloadRequest, conn=Depends(get_conn)) -> WorkloadResponse:
    """Top-N slowest queries from pg_stat_statements, each auto-analyzed."""
    try:
        reports = analyze_workload(conn, n=req.n, min_calls=req.min_calls)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workload analysis failed: {exc}")

    def _slow(s) -> SlowQueryOut:
        return SlowQueryOut(
            queryid=s.queryid,
            query=s.query,
            calls=s.calls,
            total_exec_ms=s.total_exec_ms,
            mean_exec_ms=s.mean_exec_ms,
            stddev_exec_ms=s.stddev_exec_ms,
            rows=s.rows,
        )

    return WorkloadResponse(
        queries=[_slow(r.slow) for r in reports],
        reports=[
            WorkloadReportOut(
                slow=_slow(r.slow),
                problems=[_problem_out(p) for p in r.problems],
                plan_nodes_count=r.plan_nodes_count,
                analysis_skipped_reason=r.analysis_skipped_reason,
            )
            for r in reports
        ],
    )
