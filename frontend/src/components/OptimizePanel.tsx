// Optimize overlay — the signature moment. Runs in two phases:
//
//   1. Pre-reveal: pipeline steps advance (LLM → validate → benchmark)
//      while the real /optimize fetch is in flight. Timers pace the
//      staging so the user sees what's happening; when the promise
//      resolves the parent flips `revealed` and we snap to phase 2.
//
//   2. Reveal: split diff on the left, verdict + benchmark strip on
//      the right. Speedup counts up over 600ms; latency dots cascade
//      in with a 25ms stagger. Accept / reject actions at the bottom.

import { useEffect, useMemo, useState } from "react";
import type { AppliedIndex, OptimizeResponse, PlanChange } from "../api/types";
import { lineDiff } from "../lib/diff";
import { fmtMs } from "../lib/format";
import { BenchmarkStrip, type BenchRow } from "./BenchmarkStrip";
import { DiffPane } from "./DiffPane";
import { PipelineSteps } from "./PipelineSteps";

type Kind = "ok" | "slow" | "unchanged" | "error";

interface Props {
  open: boolean;
  loading: boolean;
  result: OptimizeResponse | null;
  error: string | null;
  onClose: () => void;
  onAccept: (sql: string) => void;
  onReject: (accepted: boolean, speedup: number | null) => void;
}

function classify(result: OptimizeResponse | null, error: string | null): Kind {
  if (error) return "error";
  if (!result) return "ok";
  if (!result.valid) return "error";
  if (result.unchanged) return "unchanged";
  const s = result.speedup ?? 1;
  return s >= 1.05 ? "ok" : "slow";
}

export function OptimizePanel({ open, loading, result, error, onClose, onAccept, onReject }: Props) {
  const [stage, setStage] = useState<0 | 1 | 2 | 3>(0);
  const [runCount, setRunCount] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [speedupAnim, setSpeedupAnim] = useState(0);

  const kind = classify(result, error);

  // Drive the pre-reveal pipeline while /optimize is in flight.
  useEffect(() => {
    if (!open) {
      setStage(0);
      setRunCount(0);
      setRevealed(false);
      setSpeedupAnim(0);
      return;
    }
    if (!loading) {
      setStage(3);
      // small delay so the pipeline visually completes before reveal
      const t = setTimeout(() => setRevealed(true), 200);
      return () => clearTimeout(t);
    }
    const timers: number[] = [];
    timers.push(window.setTimeout(() => setStage(1), 1400));
    timers.push(window.setTimeout(() => setStage(2), 2300));
    // benchmark tick until the promise resolves
    let n = 0;
    const tick = () => {
      n++;
      setRunCount(n);
      if (n < 12) timers.push(window.setTimeout(tick, 120));
    };
    timers.push(window.setTimeout(tick, 2500));
    return () => timers.forEach(clearTimeout);
  }, [open, loading]);

  // Speedup count-up when revealed.
  useEffect(() => {
    if (!revealed) return;
    const target = result?.speedup ?? 0;
    if (!target) {
      setSpeedupAnim(0);
      return;
    }
    const t0 = performance.now();
    let raf = 0;
    const step = () => {
      const p = Math.min(1, (performance.now() - t0) / 600);
      setSpeedupAnim(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [revealed, result?.speedup]);

  const diff = useMemo(() => {
    if (!result) return { left: [], right: [] };
    return lineDiff(result.original_sql, result.rewritten_sql);
  }, [result]);

  const benchRows: BenchRow[] = useMemo(() => {
    if (!result?.original_benchmark || !result?.rewrite_benchmark) return [];
    const ob = result.original_benchmark;
    const nb = result.rewrite_benchmark;
    return [
      {
        label: "original",
        labelColor: "#8b94a7",
        dotColor: "#5b6474",
        p50: ob.warm_p50_ms,
        p95: ob.warm_p95_ms,
        cold: ob.cold_ms,
        runs: ob.all_runs_ms.slice(),
      },
      {
        label: "rewrite",
        labelColor: "#ffb224",
        dotColor: "#5cc8ff",
        p50: nb.warm_p50_ms,
        p95: nb.warm_p95_ms,
        cold: nb.cold_ms,
        runs: nb.all_runs_ms.slice(),
      },
    ];
  }, [result]);

  if (!open) return null;

  const speedup = result?.speedup ?? 0;
  const spShown = revealed ? speedupAnim : 0;
  const verdictColor = kind === "ok" ? "#3ecf8e" : kind === "slow" ? "#f4566a" : "#8b94a7";
  const verdictSub =
    result?.original_benchmark && result?.rewrite_benchmark
      ? `p50 warm · ${fmtMs(result.original_benchmark.warm_p50_ms)} → ${fmtMs(result.rewrite_benchmark.warm_p50_ms)}`
      : "";
  const verdictLine =
    kind === "ok"
      ? "Rewrite is faster — validated, safe to accept."
      : kind === "slow"
        ? "Rewrite is SLOWER than the original. Recommend keeping your query."
        : "";

  const specialGlyph = kind === "error" ? "✕" : "≡";
  const specialFg = kind === "error" ? "#f4566a" : "#8b94a7";
  const specialBg = kind === "error" ? "#12080b" : "#0e1218";
  const specialBorder = kind === "error" ? "#3a1620" : "#232a35";
  const specialTitle =
    kind === "error"
      ? "Rewrite failed validation — not benchmarked"
      : "LLM returned the original query unchanged";
  const specialDetail =
    kind === "error"
      ? result?.validation_error ||
        error ||
        "The model produced SQL that does not parse. No benchmark was run; nothing to accept."
      : "The model found no rewrite it was confident improves this query. That's a valid answer — your SQL is already in good shape structurally. Consider the index suggestions in Problems instead.";

  const indexCount = result?.applied_indexes?.length ?? 0;
  const pipeSteps = [
    {
      label: `Rewriting with ${result?.llm?.model ?? "llama-3.3-70b"}`,
      detail:
        stage >= 1
          ? result?.llm
            ? `${(result.llm.latency_ms / 1000).toFixed(2)}s`
            : "done"
          : stage === 0
            ? "…"
            : "",
      status: (stage > 0 ? "done" : "active") as "done" | "active" | "pending",
    },
    {
      label: "Applying suggested indexes",
      detail:
        stage >= 2
          ? indexCount === 0
            ? "no indexes"
            : `${indexCount} index${indexCount === 1 ? "" : "es"}`
          : stage === 1
            ? "…"
            : "",
      status: (stage > 1 ? "done" : stage === 1 ? "active" : "pending") as "done" | "active" | "pending",
    },
    {
      label: "Benchmarking original vs rewrite (with indexes)",
      detail: stage >= 3 ? "12/12 · dropped" : stage === 2 ? `run ${runCount}/12` : "",
      status: (stage > 2 ? "done" : stage === 2 ? "active" : "pending") as "done" | "active" | "pending",
    },
  ];

  const canAccept = kind === "ok" && !!result;
  const acceptAnyway = kind === "slow" && !!result;

  const accept = () => {
    if (!result) return;
    onAccept(result.rewritten_sql);
    onReject(true, speedup);
  };
  const reject = () => {
    onReject(false, result?.speedup ?? null);
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(6,8,11,.82)",
        backdropFilter: "blur(3px)",
        display: "flex",
        alignItems: "stretch",
        justifyContent: "center",
        padding: "26px 32px",
        zIndex: 50,
      }}
    >
      <div
        style={{
          flex: 1,
          maxWidth: 1280,
          background: "#0c0f14",
          border: "1px solid #232a35",
          borderRadius: 14,
          boxShadow: "0 24px 80px rgba(0,0,0,.6)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          animation: "odb-fadeup .18s ease-out",
        }}
      >
        <div
          style={{
            height: 46,
            flex: "none",
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "0 16px",
            borderBottom: "1px solid #1c222c",
          }}
        >
          <div style={{ fontWeight: 600 }}>Optimize result</div>
          <div style={{ fontSize: 10, fontFamily: "'JetBrains Mono', monospace", color: "#5b6474" }}>
            {loading ? "in flight" : kind}
          </div>
          <div style={{ flex: 1 }} />
          <button
            onClick={onClose}
            style={{
              width: 26,
              height: 26,
              borderRadius: 6,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              color: "#5b6474",
              border: "1px solid #232a35",
              background: "transparent",
            }}
            onMouseOver={(e) => ((e.currentTarget as HTMLButtonElement).style.color = "#e6eaf2")}
            onMouseOut={(e) => ((e.currentTarget as HTMLButtonElement).style.color = "#5b6474")}
          >
            ✕
          </button>
        </div>

        {!revealed && !result && !error && (
          <PipelineSteps
            steps={pipeSteps}
            onSkip={() => {
              setStage(3);
              setRunCount(12);
            }}
          />
        )}

        {(revealed || result || error) && (
          <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
            <div
              style={{
                flex: 1.35,
                display: "flex",
                flexDirection: "column",
                minWidth: 0,
                borderRight: "1px solid #1c222c",
              }}
            >
              <div
                style={{
                  display: "flex",
                  flex: "none",
                  borderBottom: "1px solid #151a22",
                  fontSize: 10,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: "#5b6474",
                }}
              >
                <div style={{ flex: 1, padding: "7px 14px", borderRight: "1px solid #151a22" }}>
                  original.sql
                </div>
                <div style={{ flex: 1, padding: "7px 14px", color: "#ffb224" }}>
                  rewrite.sql{" "}
                  <span style={{ color: "#5b6474" }}>— {result?.llm?.model ?? "-"}</span>
                </div>
              </div>
              {result ? (
                <DiffPane diff={diff} />
              ) : (
                <div
                  style={{
                    flex: 1,
                    padding: 24,
                    color: "#5b6474",
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 11,
                  }}
                >
                  {error || "no result"}
                </div>
              )}
              <div
                style={{
                  flex: "none",
                  display: "flex",
                  gap: 14,
                  padding: "8px 14px",
                  borderTop: "1px solid #151a22",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 10,
                  color: "#5b6474",
                }}
              >
                <span>{result?.llm?.model ?? "-"}</span>
                <span>
                  {result?.llm ? `${result.llm.input_tokens} in · ${result.llm.output_tokens} out` : "-"}
                </span>
                <span>{result?.llm ? `${(result.llm.latency_ms / 1000).toFixed(2)}s` : "-"}</span>
              </div>
            </div>

            <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "auto" }}>
              <div style={{ padding: "18px 18px 12px", borderBottom: "1px solid #151a22" }}>
                {(kind === "ok" || kind === "slow") && result && (
                  <>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                      <div
                        style={{
                          fontSize: 44,
                          fontWeight: 700,
                          fontFamily: "'JetBrains Mono', monospace",
                          color: verdictColor,
                          letterSpacing: "-.02em",
                        }}
                      >
                        {spShown.toFixed(2)}×
                      </div>
                      <div style={{ fontSize: 12, color: "#8b94a7" }}>{verdictSub}</div>
                    </div>
                    <div style={{ fontSize: 11, color: verdictColor, marginTop: 2, fontWeight: 600 }}>
                      {verdictLine}
                    </div>
                  </>
                )}
                {(kind === "unchanged" || kind === "error") && (
                  <div
                    style={{
                      display: "flex",
                      gap: 12,
                      alignItems: "flex-start",
                      padding: 14,
                      borderRadius: 9,
                      border: `1px solid ${specialBorder}`,
                      background: specialBg,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 18,
                        flex: "none",
                        fontFamily: "'JetBrains Mono', monospace",
                        color: specialFg,
                      }}
                    >
                      {specialGlyph}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 12.5, color: specialFg }}>{specialTitle}</div>
                      <div
                        style={{
                          fontSize: 11.5,
                          color: "#8b94a7",
                          marginTop: 4,
                          lineHeight: 1.6,
                          fontFamily: "'JetBrains Mono', monospace",
                        }}
                      >
                        {specialDetail}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {result && (result.applied_indexes.length > 0 || result.plan_changes.length > 0) && (
                <IndexesAndPlan
                  applied={result.applied_indexes}
                  changes={result.plan_changes}
                  leaks={result.cleanup_leaks}
                  rejected={result.rejected_ddl}
                />
              )}

              {benchRows.length > 0 && <BenchmarkStrip rows={benchRows} revealed={revealed} />}

              <div style={{ flex: 1 }} />

              <div
                style={{
                  flex: "none",
                  display: "flex",
                  gap: 8,
                  padding: "14px 18px",
                  borderTop: "1px solid #151a22",
                }}
              >
                {canAccept && (
                  <button
                    onClick={accept}
                    style={{
                      padding: "8px 16px",
                      borderRadius: 7,
                      background: "#3ecf8e",
                      color: "#06281a",
                      fontWeight: 700,
                      fontSize: 12,
                      cursor: "pointer",
                      border: "none",
                    }}
                    onMouseOver={(e) => ((e.currentTarget as HTMLButtonElement).style.filter = "brightness(1.08)")}
                    onMouseOut={(e) => ((e.currentTarget as HTMLButtonElement).style.filter = "none")}
                  >
                    Accept rewrite
                  </button>
                )}
                {acceptAnyway && (
                  <button
                    onClick={accept}
                    style={{
                      padding: "8px 16px",
                      borderRadius: 7,
                      border: "1px solid #232a35",
                      color: "#8b94a7",
                      fontSize: 12,
                      cursor: "pointer",
                      background: "transparent",
                    }}
                    onMouseOver={(e) => ((e.currentTarget as HTMLButtonElement).style.color = "#e6eaf2")}
                    onMouseOut={(e) => ((e.currentTarget as HTMLButtonElement).style.color = "#8b94a7")}
                  >
                    Accept anyway
                  </button>
                )}
                <button
                  onClick={reject}
                  style={{
                    padding: "8px 16px",
                    borderRadius: 7,
                    border: `1px solid ${kind === "slow" ? "#3ecf8e" : "#232a35"}`,
                    color: kind === "slow" ? "#3ecf8e" : "#8b94a7",
                    fontSize: 12,
                    cursor: "pointer",
                    fontWeight: kind === "slow" ? 700 : 400,
                    background: "transparent",
                  }}
                  onMouseOver={(e) =>
                    ((e.currentTarget as HTMLButtonElement).style.borderColor = "#3a4557")
                  }
                  onMouseOut={(e) =>
                    ((e.currentTarget as HTMLButtonElement).style.borderColor =
                      kind === "slow" ? "#3ecf8e" : "#232a35")
                  }
                >
                  {kind === "ok" ? "Reject" : kind === "slow" ? "Keep original" : "Close"}
                </button>
                <div style={{ flex: 1 }} />
                <div
                  style={{
                    alignSelf: "center",
                    fontSize: 10,
                    color: "#3a4152",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  esc to close
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// -------- Indexes + plan-change sub-panel --------
// Sits between the verdict and the benchmark strip. This is the
// "proof": here's exactly what we changed on your DB, and here's the
// plan-shape shift that resulted. Everything is dropped by the time
// this renders — cleanup_leaks calls out anything that didn't.

interface IndexesAndPlanProps {
  applied: AppliedIndex[];
  changes: PlanChange[];
  leaks: string[];
  rejected: string[];
}

function IndexesAndPlan({ applied, changes, leaks, rejected }: IndexesAndPlanProps) {
  // Set of relations for which we actually created an index. Used to
  // distinguish "planner chose seq scan even though an index exists"
  // (a legitimate choice for high-selectivity scans) from "no index
  // was ever tried" (a null result).
  const indexedRelations = new Set(
    applied.filter((ix) => ix.applied).map((ix) => ix.table.toLowerCase()),
  );
  const Overline = ({ children }: { children: React.ReactNode }) => (
    <div
      style={{
        fontSize: 10,
        fontFamily: "'JetBrains Mono', monospace",
        color: "#5b6474",
        textTransform: "uppercase",
        letterSpacing: ".08em",
        marginBottom: 8,
      }}
    >
      {children}
    </div>
  );

  return (
    <div style={{ padding: "14px 18px", borderBottom: "1px solid #151a22" }}>
      {applied.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <Overline>
            Applied indexes{" "}
            <span style={{ color: "#3a4152", textTransform: "none", letterSpacing: 0 }}>
              · created, benchmarked, then dropped
            </span>
          </Overline>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {applied.map((ix) => {
              const ok = ix.applied;
              return (
                <div
                  key={ix.tmp_name}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    padding: "6px 10px",
                    border: `1px solid ${ok ? "#151a22" : "#3a1620"}`,
                    borderRadius: 6,
                    background: ok ? "#0e1218" : "#12080b",
                  }}
                >
                  <span
                    style={{
                      flex: "none",
                      marginTop: 1,
                      fontFamily: "'JetBrains Mono', monospace",
                      color: ok ? "#3ecf8e" : "#f4566a",
                      fontWeight: 700,
                      fontSize: 11,
                    }}
                  >
                    {ok ? "✓" : "✕"}
                  </span>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div
                      style={{
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: 11,
                        color: "#e6eaf2",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      <span style={{ color: "#5cc8ff" }}>{ix.table}</span>
                      <span style={{ color: "#8b94a7" }}> (</span>
                      <span style={{ color: "#e6eaf2" }}>{ix.columns}</span>
                      <span style={{ color: "#8b94a7" }}>)</span>
                    </div>
                    <div
                      style={{
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: 10,
                        color: "#5b6474",
                        marginTop: 2,
                      }}
                    >
                      {ok ? ix.tmp_name : ix.error || "not applied"}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {changes.length > 0 && (
        <div>
          <Overline>Plan changes · before → after</Overline>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {changes.map((c) => {
              // "Planner choice" = an index was created for this relation
              // but the planner picked seq scan anyway. That's usually
              // correct: index scan loses when the query returns a large
              // fraction of the table's rows. We surface it explicitly
              // so users don't wonder why the index "didn't work".
              const plannerChoice =
                !c.changed && indexedRelations.has(c.relation.toLowerCase());
              return (
                <div
                  key={c.relation}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "6px 10px",
                    border: "1px solid #151a22",
                    borderRadius: 6,
                    background: c.changed ? "rgba(62,207,142,.05)" : "transparent",
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 11,
                  }}
                >
                  <span style={{ color: "#5cc8ff", minWidth: 100 }}>{c.relation}</span>
                  <span style={{ color: /seq scan/i.test(c.before_node_type) ? "#d9a53d" : "#8b94a7" }}>
                    {c.before_node_type}
                  </span>
                  <span style={{ color: "#3a4152" }}>→</span>
                  <span
                    style={{
                      color: c.changed && /index/i.test(c.after_node_type) ? "#3ecf8e" : "#8b94a7",
                      fontWeight: c.changed ? 600 : 400,
                    }}
                  >
                    {c.after_node_type}
                  </span>
                  {c.changed && (
                    <span
                      style={{
                        marginLeft: "auto",
                        padding: "1px 6px",
                        borderRadius: 4,
                        fontSize: 9,
                        color: "#3ecf8e",
                        background: "rgba(62,207,142,.12)",
                        fontWeight: 700,
                      }}
                    >
                      CHANGED
                    </span>
                  )}
                  {plannerChoice && (
                    <span
                      title="Seq Scan chosen intentionally — the planner considered the index we created but a full scan is cheaper here (large fraction of rows returned). This is correct behaviour."
                      style={{
                        marginLeft: "auto",
                        padding: "1px 6px",
                        borderRadius: 4,
                        fontSize: 9,
                        color: "#8b94a7",
                        background: "#151a22",
                        fontWeight: 600,
                        letterSpacing: ".05em",
                        cursor: "help",
                      }}
                    >
                      PLANNER CHOICE
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {leaks.length > 0 && (
        <div
          style={{
            marginTop: 12,
            padding: "8px 10px",
            border: "1px solid #3a1620",
            background: "#12080b",
            borderRadius: 6,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10.5,
            color: "#f4566a",
          }}
        >
          Cleanup failed for {leaks.length} index{leaks.length === 1 ? "" : "es"}. Drop manually:
          <div style={{ color: "#e6eaf2", marginTop: 4 }}>
            {leaks.map((n) => `DROP INDEX ${n};`).join("  ")}
          </div>
        </div>
      )}

      {rejected.length > 0 && (
        <div
          style={{
            marginTop: 12,
            padding: "8px 10px",
            border: "1px solid #232a35",
            borderRadius: 6,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10.5,
            color: "#8b94a7",
          }}
        >
          LLM emitted {rejected.length} non-index statement{rejected.length === 1 ? "" : "s"} —
          rejected by the allowlist.
        </div>
      )}
    </div>
  );
}
