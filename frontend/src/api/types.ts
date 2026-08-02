// TypeScript mirrors of backend Pydantic schemas. Keep these in sync
// with project/backend/api/schemas.py — if you change one side, change both.

export type Severity = "HIGH" | "MEDIUM";
export type ProblemType =
  | "SEQ_SCAN_LARGE"
  | "ROW_ESTIMATE_ERROR"
  | "NESTED_LOOP_HIGH_ROWS"
  | "MISSING_INDEX_CANDIDATE"
  | "STALE_STATISTICS"
  | "CROSS_JOIN_RISK";

export interface PlanNode {
  node_type: string;
  relation_name: string | null;
  startup_cost: number;
  total_cost: number;
  plan_rows: number;
  actual_rows: number;
  actual_loops: number;
  filter: string | null;
  depth: number;
}

export interface Problem {
  type: ProblemType | string;
  severity: Severity;
  message: string;
  node_type: string;
  relation_name: string | null;
}

export interface Benchmark {
  n: number;
  cold_ms: number;
  warm_p50_ms: number;
  warm_p95_ms: number;
  warm_min_ms: number;
  warm_max_ms: number;
  all_runs_ms: number[];
}

export interface LLMInfo {
  model: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
}

export interface AnalyzeResponse {
  query: string;
  plan_nodes: PlanNode[];
  problems: Problem[];
  planning_ms: number;
  execution_ms: number;
  blocked_reason?: string | null;
}

export interface AppliedIndex {
  tmp_name: string;
  original_name: string | null;
  table: string;
  columns: string;
  ddl: string;
  applied: boolean;
  error: string | null;
}

export interface PlanChange {
  relation: string;
  before_node_type: string;
  after_node_type: string;
  changed: boolean;
}

export interface OptimizeResponse {
  original_sql: string;
  rewritten_sql: string;
  valid: boolean;
  unchanged: boolean;
  validation_error: string | null;
  llm: LLMInfo | null;
  original_benchmark: Benchmark | null;
  rewrite_benchmark: Benchmark | null;
  speedup: number | null;
  problems: Problem[];
  applied_indexes: AppliedIndex[];
  rejected_ddl: string[];
  plan_changes: PlanChange[];
  cleanup_leaks: string[];
  blocked_reason?: string | null;
}

export interface HealthResponse {
  ok: boolean;
  postgres: boolean;
  detail: string | null;
}

export interface SlowQuery {
  queryid: string;
  query: string;
  calls: number;
  total_exec_ms: number;
  mean_exec_ms: number;
  stddev_exec_ms: number;
  rows: number;
}

export interface WorkloadReport {
  slow: SlowQuery;
  problems: Problem[];
  plan_nodes_count: number;
  analysis_skipped_reason: string | null;
}

export interface WorkloadResponse {
  queries: SlowQuery[];
  reports: WorkloadReport[];
}
