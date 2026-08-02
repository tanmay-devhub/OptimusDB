// Log-scale latency distribution strip — the "signature moment". Renders
// each individual warm run as a dot, p50/p95 as vertical marks, cold as
// a rotated diamond. Reveal is staggered: p50/p95 first, then cold, then
// dots cascade at 25ms intervals per row.

import { fmtMs } from "../lib/format";

export interface BenchRow {
  label: string;
  labelColor: string;
  dotColor: string;
  p50: number;
  p95: number;
  cold: number;
  runs: number[];
}

interface Props {
  rows: BenchRow[];
  revealed: boolean;
}

export function BenchmarkStrip({ rows, revealed }: Props) {
  if (!rows.length) return null;

  // Shared log axis across both rows so bars are directly comparable.
  const allValues = rows.flatMap((r) => r.runs.concat([r.cold]));
  const lo = Math.min(...allValues) * 0.85;
  const hi = Math.max(...allValues) * 1.15;
  const X = (v: number) => (Math.log(Math.max(v, 1e-3) / lo) / Math.log(hi / lo)) * 94 + 3;

  const axisMin = fmtMs(lo);
  const axisMid = fmtMs(Math.sqrt(lo * hi));
  const axisMax = fmtMs(hi);

  return (
    <div style={{ padding: "14px 18px" }}>
      <div
        style={{
          fontSize: 10,
          fontFamily: "'JetBrains Mono', monospace",
          color: "#5b6474",
          textTransform: "uppercase",
          letterSpacing: ".08em",
          marginBottom: 12,
        }}
      >
        Latency distribution · {rows[0].runs.length} warm runs + cold{" "}
        <span style={{ color: "#3a4152" }}>log scale</span>
      </div>

      {rows.map((r, bi) => (
        <div key={bi} style={{ marginBottom: 20 }}>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 10,
              marginBottom: 6,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            <span style={{ fontSize: 11, color: r.labelColor, fontWeight: 600, width: 64 }}>{r.label}</span>
            <span style={{ fontSize: 10, color: "#5b6474" }}>
              p50 <span style={{ color: "#e6eaf2" }}>{fmtMs(r.p50)}</span>
            </span>
            <span style={{ fontSize: 10, color: "#5b6474" }}>
              p95 <span style={{ color: "#e6eaf2" }}>{fmtMs(r.p95)}</span>
            </span>
            <span style={{ fontSize: 10, color: "#5b6474" }}>
              cold <span style={{ color: "#e6eaf2" }}>{fmtMs(r.cold)}</span>
            </span>
          </div>
          <div
            style={{
              position: "relative",
              height: 34,
              background: "#0a0c10",
              border: "1px solid #151a22",
              borderRadius: 6,
            }}
          >
            <div
              title="p50"
              style={{
                position: "absolute",
                top: 4,
                bottom: 4,
                left: `${X(r.p50).toFixed(1)}%`,
                width: 2,
                background: r.dotColor,
                opacity: revealed ? 1 : 0,
                transition: "opacity .4s ease .5s",
              }}
            />
            <div
              title="p95"
              style={{
                position: "absolute",
                top: 4,
                bottom: 4,
                left: `${X(r.p95).toFixed(1)}%`,
                width: 2,
                background: r.dotColor,
                opacity: revealed ? 0.5 : 0,
                transition: "opacity .4s ease .6s",
              }}
            />
            <div
              title="cold run"
              style={{
                position: "absolute",
                top: "50%",
                left: `${X(r.cold).toFixed(1)}%`,
                width: 8,
                height: 8,
                background: "#8b94a7",
                transform: "translate(-50%,-50%) rotate(45deg)",
                opacity: revealed ? 1 : 0,
                transition: "opacity .4s ease .7s",
              }}
            />
            {r.runs.map((v, ri) => {
              const delay = `${(bi * 0.15 + ri * 0.025).toFixed(3)}s`;
              return (
                <div
                  key={ri}
                  title={`run ${ri + 1} · ${fmtMs(v)}`}
                  style={{
                    position: "absolute",
                    top: "50%",
                    left: `${X(v).toFixed(1)}%`,
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: r.dotColor,
                    opacity: revealed ? 0.85 : 0,
                    transform: `translate(-50%,-50%) scale(${revealed ? 1 : 0.3})`,
                    transition: `opacity .3s ease ${delay}, transform .3s ease ${delay}`,
                  }}
                />
              );
            })}
          </div>
        </div>
      ))}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 9.5,
          color: "#3a4152",
          marginTop: -10,
        }}
      >
        <span>{axisMin}</span>
        <span>{axisMid}</span>
        <span>{axisMax}</span>
      </div>

      <div
        style={{
          display: "flex",
          gap: 16,
          marginTop: 14,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
          color: "#5b6474",
          alignItems: "center",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#5cc8ff", display: "inline-block" }} />
          warm run
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span
            style={{
              width: 7,
              height: 7,
              background: "#8b94a7",
              display: "inline-block",
              transform: "rotate(45deg)",
            }}
          />
          cold
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 2, height: 10, background: "#5cc8ff", display: "inline-block" }} />
          p50 / p95
        </span>
      </div>
    </div>
  );
}
