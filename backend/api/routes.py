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

import logging

from fastapi import APIRouter, Depends, HTTPException

from analyzer.batch import analyze_workload
from analyzer.detector import Problem, ProblemType, Severity, detect_problems
from analyzer.indexes import (
    apply_indexes,
    drop_indexes,
    hypothesize_indexes,
    reset_hypothetical,
)
from analyzer.plan_parser import (
    PlanNode,
    detect_cross_join_risk,
    parse_plan,
    run_explain,
    run_explain_planner_only,
)
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


logger = logging.getLogger(__name__)

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


def _root_total_cost(nodes: list[PlanNode]) -> float | None:
    """Total planner cost of the plan root, or None for an empty plan."""
    return nodes[0].total_cost if nodes else None


def _index_out(s) -> IndexOut:
    """Copy an IndexSuggestion (physical or hypothetical) to its wire schema."""
    return IndexOut(
        tmp_name=s.tmp_name,
        original_name=s.original_name,
        table=s.table,
        columns=s.columns,
        ddl=s.ddl,
        applied=s.applied,
        error=s.error,
        hypopg_oid=s.hypopg_oid,
    )


@router.post("/optimize", response_model=OptimizeResponse)
def optimize(req: QueryRequest, conn=Depends(get_conn)) -> OptimizeResponse:
    """Analyze → LLM rewrite (+ index suggestions) → apply indexes →
    benchmark both → drop indexes → verdict.

    Two modes selected by ``req.mode``:

    * ``"measure"`` (default) — physical CREATE INDEX + wall-clock
      benchmark of both queries + DROP INDEX. Accurate but slow, and
      unsafe on huge tables. Retained for the current TPC-H story and
      any staging-scale run.
    * ``"hypothetical"`` — HypoPG hypothetical indexes + planner-cost
      comparison. Zero disk writes, zero locks, safe on any DB size.
      Verdict is a ``cost_ratio`` not a ``speedup``.

    In measure mode the DB is mutated (CREATE INDEX) and then restored
    (DROP INDEX) within this single request. If cleanup fails, the tmp
    names are reported in ``cleanup_leaks``. Hypothetical mode cannot
    leak anything - HypoPG state is session-local and reset before
    returning.
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
            mode=req.mode,
            original_benchmark=None,
            rewrite_benchmark=None,
            speedup=None,
            cost_ratio=None,
            original_total_cost=None,
            rewrite_total_cost=None,
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
    original_total_cost = _root_total_cost(nodes_before)

    try:
        rewrite = optimize_query(req.query, problems, nodes_before, conn)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    orig_b: BenchmarkOut | None = None
    new_b: BenchmarkOut | None = None
    speedup: float | None = None
    cost_ratio: float | None = None
    rewrite_total_cost: float | None = None
    plan_changes: list[PlanChangeOut] = []
    cleanup_leaks: list[str] = []

    # --- Hypothetical mode ----------------------------------------------
    # Route the entire post-rewrite path through HypoPG. No physical DDL,
    # no benchmark harness, no cleanup_leaks bookkeeping - the planner
    # cost delta is the verdict.
    if rewrite.valid and req.mode == "hypothetical":
        # HypoPG hypothetical indexes only exist in the planner's mind -
        # they cannot be physically read. So we MUST use planner-only
        # EXPLAIN (no ANALYZE) here, or the planner falls back to
        # Seq Scan and the hypothetical index is invisible in the plan.
        # For symmetry we also re-cost the original plan without ANALYZE
        # so the ratio compares like-for-like.
        try:
            raw_orig_planner = run_explain_planner_only(req.query, conn)
            original_total_cost = _root_total_cost(parse_plan(raw_orig_planner))
        except Exception:
            pass
        try:
            hypothesize_indexes(conn, rewrite.index_suggestions)
            try:
                raw_after = run_explain_planner_only(rewrite.rewritten_sql, conn)
                nodes_after = parse_plan(raw_after)
                rewrite_total_cost = _root_total_cost(nodes_after)
                plan_changes = _plan_changes(nodes_before, nodes_after)
            except Exception:
                # Rewrite validated moments ago; a fresh EXPLAIN failure
                # here would be surprising but not fatal.
                plan_changes = []
            if (
                original_total_cost is not None
                and rewrite_total_cost is not None
                and rewrite_total_cost > 0
            ):
                cost_ratio = original_total_cost / rewrite_total_cost
        finally:
            reset_hypothetical(conn)

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
            mode="hypothetical",
            original_benchmark=None,
            rewrite_benchmark=None,
            speedup=None,
            cost_ratio=cost_ratio,
            original_total_cost=original_total_cost,
            rewrite_total_cost=rewrite_total_cost,
            problems=[_problem_out(p) for p in problems],
            applied_indexes=[_index_out(s) for s in rewrite.index_suggestions],
            rejected_ddl=rewrite.rejected_ddl,
            plan_changes=plan_changes,
            cleanup_leaks=[],
        )

    # --- Measure mode (default, unchanged behavior) ---------------------
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
                rewrite_total_cost = _root_total_cost(nodes_after)
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

        # 6. Post-cleanup verify. If any optimusdb_tmp_ index survives
        #    here, either drop_indexes swallowed an exception or the
        #    caller passed a suggestion list that didn't cover something
        #    apply_indexes created. Log loudly so leaks surface in the
        #    server log the moment they happen instead of accumulating.
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM pg_indexes "
                    "WHERE indexname LIKE 'optimusdb_tmp_%'"
                )
                remaining = int(cur.fetchone()[0])
            if remaining > 0:
                logger.error(
                    "LEAK DETECTED: %d optimusdb_tmp_ index(es) remain after cleanup "
                    "(reported cleanup_leaks=%s)",
                    remaining, cleanup_leaks,
                )
        except Exception:
            logger.exception("Post-cleanup leak-verify query failed")

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
        mode="measure",
        original_benchmark=orig_b,
        rewrite_benchmark=new_b,
        speedup=speedup,
        cost_ratio=None,
        original_total_cost=original_total_cost,
        rewrite_total_cost=rewrite_total_cost,
        problems=[_problem_out(p) for p in problems],
        applied_indexes=[_index_out(s) for s in rewrite.index_suggestions],
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
