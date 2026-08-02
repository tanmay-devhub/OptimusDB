// History — session entries persisted to localStorage. ANALYZE and
// OPTIMIZE rows show timestamps, first-line SQL, speedup when present,
// and a verdict tag (accepted / rejected / N problems).

import type { HistoryEntry } from "../lib/history";
import { hhmm } from "../lib/format";

interface Props {
  entries: HistoryEntry[];
  onClear: () => void;
}

export function HistoryView({ entries, onClear }: Props) {
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
        <div style={{ fontWeight: 600 }}>History</div>
        <div style={{ fontSize: 10, fontFamily: "'JetBrains Mono', monospace", color: "#5b6474" }}>
          persisted to localStorage · survives refresh
        </div>
        <div style={{ flex: 1 }} />
        <button
          onClick={onClear}
          style={{
            padding: "4px 10px",
            borderRadius: 5,
            border: "1px solid #232a35",
            color: "#5b6474",
            fontSize: 10.5,
            cursor: "pointer",
            background: "transparent",
          }}
          onMouseOver={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color = "#f4566a";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "#3a1620";
          }}
          onMouseOut={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color = "#5b6474";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "#232a35";
          }}
        >
          Clear session
        </button>
      </div>

      <div className="scroll-y" style={{ flex: 1, overflow: "auto", padding: "10px 14px" }}>
        {entries.length === 0 && (
          <div style={{ padding: "60px 0", textAlign: "center", color: "#5b6474", fontSize: 12 }}>
            Nothing yet — analyze or optimize a query and it lands here.
          </div>
        )}
        {entries.map((h, i) => {
          const opt = h.kind === "OPTIMIZE";
          const kindFg = opt ? "#ffb224" : "#5cc8ff";
          const kindBg = opt ? "rgba(255,178,36,.12)" : "rgba(92,200,255,.1)";
          const hasSpeedup = h.speedup != null;
          const spColor = (h.speedup ?? 0) >= 1 ? "#3ecf8e" : "#f4566a";
          const verdictColor = h.verdict === "accepted" ? "#3ecf8e" : "#5b6474";
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "9px 12px",
                border: "1px solid #151a22",
                borderRadius: 8,
                marginBottom: 6,
                background: "#0c0f14",
              }}
            >
              <div
                style={{
                  flex: "none",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 10,
                  color: "#5b6474",
                  width: 56,
                }}
              >
                {hhmm(h.ts)}
              </div>
              <div
                style={{
                  flex: "none",
                  padding: "1px 7px",
                  borderRadius: 4,
                  fontSize: 9,
                  fontWeight: 700,
                  fontFamily: "'JetBrains Mono', monospace",
                  letterSpacing: ".05em",
                  color: kindFg,
                  background: kindBg,
                }}
              >
                {h.kind}
              </div>
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
                {h.sql}
              </div>
              {hasSpeedup && (
                <div
                  style={{
                    flex: "none",
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 11,
                    fontWeight: 700,
                    color: spColor,
                  }}
                >
                  {(h.speedup ?? 0).toFixed(2)}×
                </div>
              )}
              <div
                style={{
                  flex: "none",
                  fontSize: 10,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: verdictColor,
                  width: 90,
                  textAlign: "right",
                }}
              >
                {h.verdict || ""}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
