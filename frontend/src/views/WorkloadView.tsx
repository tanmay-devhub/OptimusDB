// Workload — top-N slowest queries from pg_stat_statements. Sortable
// by impact / calls / mean. Parameterized statements ($1, $2 …) can't
// be re-EXPLAIN'd honestly; those get a "paste values" affordance
// instead of an analyze button. The hourly heat cells are derived
// deterministically from the queryid (pg_stat_statements doesn't
// expose hourly breakdown) — they're an activity signature, not
// literal per-hour counts.

import { useEffect, useMemo, useState } from "react";
import { workload as fetchWorkload } from "../api/client";
import type { WorkloadReport, WorkloadResponse } from "../api/types";
import { fmtDur, fmtN } from "../lib/format";
import { SqlText } from "../lib/sql";
import { ScanLoader } from "../components/ScanLoader";

type SortKey = "impact" | "calls" | "mean";

interface Props {
  onOpenInEditor: (sql: string, mode: "analyze" | "paste") => void;
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function heat(seed: number): number[] {
  const a: number[] = [];
  for (let i = 0; i < 24; i++) {
    const x = Math.sin(seed * 97.7 + i * 13.3) * 0.5 + 0.5;
    a.push(x > 0.55 ? +x.toFixed(2) : x > 0.4 ? 0.1 : 0);
  }
  return a;
}

export function WorkloadView({ onOpenInEditor }: Props) {
  const [data, setData] = useState<WorkloadResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("impact");

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    fetchWorkload(8, 1, ac.signal)
      .then((r) => {
        setData(r);
        setError(null);
      })
      .catch((e) => {
        if (e.name === "AbortError") return;
        setError(String(e.message ?? e));
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, []);

  const rows = useMemo<WorkloadReport[]>(() => {
    if (!data) return [];
    const cmp = {
      impact: (a: WorkloadReport, b: WorkloadReport) => b.slow.total_exec_ms - a.slow.total_exec_ms,
      calls: (a: WorkloadReport, b: WorkloadReport) => b.slow.calls - a.slow.calls,
      mean: (a: WorkloadReport, b: WorkloadReport) => b.slow.mean_exec_ms - a.slow.mean_exec_ms,
    }[sort];
    return data.reports.slice().sort(cmp);
  }, [data, sort]);

  const maxTotal = Math.max(1, ...rows.map((r) => r.slow.total_exec_ms));

  const chipStyle = (active: boolean) => ({
    padding: "3px 9px",
    borderRadius: 5,
    fontSize: 10,
    fontFamily: "'JetBrains Mono', monospace",
    cursor: "pointer",
    border: `1px solid ${active ? "#2b3a4a" : "#1c222c"}`,
    color: active ? "#5cc8ff" : "#5b6474",
    background: active ? "rgba(92,200,255,.07)" : "transparent",
    whiteSpace: "nowrap" as const,
    flex: "none" as const,
  });

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
      <div
        style={{
          height: 44,
          flex: "none",
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "0 14px",
          borderBottom: "1px solid #1c222c",
          background: "#0c0f14",
        }}
      >
        <div style={{ fontWeight: 600 }}>Workload</div>
        <div style={{ fontSize: 10, fontFamily: "'JetBrains Mono', monospace", color: "#5b6474" }}>
          pg_stat_statements · top {rows.length || "N"} by total exec time
        </div>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: "#5b6474", fontFamily: "'JetBrains Mono', monospace" }}>sort</span>
        {(["impact", "calls", "mean"] as SortKey[]).map((s) => (
          <button
            key={s}
            onClick={() => setSort(s)}
            style={{ ...chipStyle(sort === s), background: sort === s ? "rgba(92,200,255,.07)" : "transparent" }}
          >
            {s === "mean" ? "mean ms" : s}
          </button>
        ))}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "6px 14px",
          borderBottom: "1px solid #151a22",
          fontSize: 9.5,
          fontFamily: "'JetBrains Mono', monospace",
          color: "#5b6474",
          textTransform: "uppercase",
          letterSpacing: ".07em",
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>query</div>
        <div style={{ width: 130, textAlign: "right", flex: "none" }}>impact</div>
        <div style={{ width: 80, textAlign: "right", flex: "none" }}>calls</div>
        <div style={{ width: 80, textAlign: "right", flex: "none" }}>mean ms</div>
        <div style={{ width: 150, textAlign: "center", flex: "none" }}>activity signature</div>
        <div style={{ width: 60, textAlign: "center", flex: "none" }}>probs</div>
        <div style={{ width: 150, flex: "none" }} />
      </div>

      <div className="scroll-y" style={{ flex: 1, overflow: "auto" }}>
        {loading && (
          <div style={{ padding: "60px 0", display: "flex", justifyContent: "center" }}>
            <ScanLoader />
          </div>
        )}
        {error && (
          <div
            style={{
              margin: 14,
              padding: 12,
              border: "1px solid #3a1620",
              background: "#12080b",
              borderRadius: 8,
              color: "#f4566a",
              fontSize: 11.5,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            /workload failed: {error}
          </div>
        )}

        {!loading && !error && rows.length === 0 && (
          <div style={{ padding: "60px 0", textAlign: "center", color: "#5b6474", fontSize: 12 }}>
            pg_stat_statements returned no rows. Run some queries first.
          </div>
        )}

        {rows.map((wr, i) => {
          const skipped = !!wr.analysis_skipped_reason;
          const pct = Math.max(3, Math.round((100 * wr.slow.total_exec_ms) / maxTotal));
          const ratio = wr.slow.total_exec_ms / maxTotal;
          const impactColor = ratio > 0.6 ? "#f4566a" : ratio > 0.25 ? "#d9a53d" : "#3a4557";
          const heatBuckets = heat(hash(wr.slow.queryid));
          const maxH = Math.max(0.01, ...heatBuckets);
          const probs = wr.problems.length;
          const probColor = skipped ? "#3a4152" : probs > 2 ? "#f4566a" : "#d9a53d";
          const probBg = skipped
            ? "transparent"
            : probs > 2
              ? "rgba(244,86,106,.12)"
              : "rgba(217,165,61,.1)";

          return (
            <div
              key={wr.slow.queryid + i}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "9px 14px",
                borderBottom: "1px solid #12161d",
              }}
              onMouseOver={(e) => ((e.currentTarget as HTMLDivElement).style.background = "#0e1218")}
              onMouseOut={(e) => ((e.currentTarget as HTMLDivElement).style.background = "transparent")}
            >
              <div
                style={{
                  flex: 1,
                  minWidth: 0,
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  color: "#c7cedb",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                <SqlText sql={wr.slow.query.replace(/\s+/g, " ").trim()} />
              </div>
              <div
                style={{
                  width: 130,
                  flex: "none",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                  gap: 8,
                }}
              >
                <div
                  style={{
                    width: 60,
                    height: 4,
                    borderRadius: 2,
                    background: "#151a22",
                    overflow: "hidden",
                  }}
                >
                  <div style={{ height: "100%", width: `${pct}%`, background: impactColor }} />
                </div>
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 10.5,
                    color: "#e6eaf2",
                    width: 52,
                    textAlign: "right",
                  }}
                >
                  {fmtDur(wr.slow.total_exec_ms)}
                </span>
              </div>
              <div
                style={{
                  width: 80,
                  flex: "none",
                  textAlign: "right",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 10.5,
                  color: "#8b94a7",
                }}
              >
                {fmtN(wr.slow.calls)}
              </div>
              <div
                style={{
                  width: 80,
                  flex: "none",
                  textAlign: "right",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 10.5,
                  color: "#8b94a7",
                }}
              >
                {wr.slow.mean_exec_ms.toFixed(wr.slow.mean_exec_ms < 10 ? 2 : 0)}
              </div>
              <div
                style={{
                  width: 150,
                  flex: "none",
                  display: "flex",
                  justifyContent: "center",
                  gap: 1,
                  padding: "0 8px",
                }}
              >
                {heatBuckets.map((v, hi) => (
                  <div
                    key={hi}
                    title={`signature bucket ${hi}`}
                    style={{
                      width: 4,
                      height: 14,
                      borderRadius: 1,
                      background:
                        v === 0
                          ? "#12161d"
                          : `rgba(244,86,106,${(0.12 + 0.85 * (v / maxH)).toFixed(2)})`,
                    }}
                  />
                ))}
              </div>
              <div style={{ width: 60, flex: "none", textAlign: "center" }}>
                <span
                  style={{
                    padding: "1px 7px",
                    borderRadius: 4,
                    fontSize: 10,
                    fontFamily: "'JetBrains Mono', monospace",
                    color: probColor,
                    background: probBg,
                  }}
                >
                  {skipped ? "—" : String(probs)}
                </span>
              </div>
              <div style={{ width: 150, flex: "none", display: "flex", justifyContent: "flex-end" }}>
                {skipped ? (
                  <button
                    onClick={() => onOpenInEditor(wr.slow.query, "paste")}
                    title={wr.analysis_skipped_reason || ""}
                    style={{
                      padding: "3px 10px",
                      borderRadius: 5,
                      border: "1px dashed #232a35",
                      color: "#5b6474",
                      fontSize: 10.5,
                      cursor: "pointer",
                      whiteSpace: "nowrap",
                      background: "transparent",
                    }}
                    onMouseOver={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.color = "#8b94a7";
                      (e.currentTarget as HTMLButtonElement).style.borderColor = "#3a4557";
                    }}
                    onMouseOut={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.color = "#5b6474";
                      (e.currentTarget as HTMLButtonElement).style.borderColor = "#232a35";
                    }}
                  >
                    $1 → paste values
                  </button>
                ) : (
                  <button
                    onClick={() => onOpenInEditor(wr.slow.query, "analyze")}
                    style={{
                      padding: "3px 10px",
                      borderRadius: 5,
                      border: "1px solid #2b3a4a",
                      color: "#5cc8ff",
                      fontSize: 10.5,
                      cursor: "pointer",
                      whiteSpace: "nowrap",
                      background: "transparent",
                    }}
                    onMouseOver={(e) =>
                      ((e.currentTarget as HTMLButtonElement).style.background = "rgba(92,200,255,.08)")
                    }
                    onMouseOut={(e) =>
                      ((e.currentTarget as HTMLButtonElement).style.background = "transparent")
                    }
                  >
                    Analyze →
                  </button>
                )}
              </div>
            </div>
          );
        })}

        {!loading && rows.length > 0 && (
          <div
            style={{
              padding: "10px 14px",
              fontSize: 10.5,
              color: "#5b6474",
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            Parameterized statements ($1, $2 …) can't be EXPLAIN ANALYZEd honestly — paste concrete
            values to analyze them.
          </div>
        )}
      </div>
    </div>
  );
}
