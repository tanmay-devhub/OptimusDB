// Problems panel — severity-chipped cards that hover-highlight the
// relation in the SQL editor and click-select a plan node.
//
// STALE_STATISTICS carries a runnable "ANALYZE <table>;" command in its
// message; we pull it out into a copyable code snippet so the user can
// paste it into psql / their client without hand-selecting.

import { useState } from "react";
import type { Problem } from "../api/types";
import { sev } from "../lib/tokens";

// Match trailing ANALYZE command (e.g. "Run: ANALYZE lineitem;") so we
// can offer a copy affordance separate from the message body.
const ANALYZE_CMD_RE = /(ANALYZE\s+[A-Za-z_][A-Za-z0-9_,\s]*;)/i;

function extractAnalyzeCommand(message: string): string | null {
  const m = message.match(ANALYZE_CMD_RE);
  return m ? m[1] : null;
}

interface Props {
  problems: Problem[];
  selectedNode: number | null;
  onSelect: (idx: number) => void;
  onHoverRel: (rel: string | null) => void;
}

export function ProblemsList({ problems, selectedNode, onSelect, onHoverRel }: Props) {
  const [copied, setCopied] = useState<number | null>(null);
  const chip = (sv: string) => {
    if (sv === "HIGH") return { fg: sev.high, bg: sev.highBg };
    return { fg: sev.medium, bg: sev.mediumBg };
  };

  const copyCmd = (idx: number, cmd: string) => {
    navigator.clipboard.writeText(cmd).then(() => {
      setCopied(idx);
      window.setTimeout(() => setCopied((c) => (c === idx ? null : c)), 1400);
    });
  };

  return (
    <div style={{ flex: "none", borderBottom: "1px solid #1c222c" }}>
      <div
        style={{
          height: 30,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "0 12px",
          fontSize: 10,
          fontFamily: "'JetBrains Mono', monospace",
          color: "#5b6474",
          textTransform: "uppercase",
          letterSpacing: ".08em",
        }}
      >
        Problems <span style={{ color: problems.length ? sev.high : "#5b6474" }}>({problems.length})</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", padding: "0 8px 8px", gap: 4 }}>
        {problems.length === 0 && (
          <div style={{ padding: "6px 10px", fontSize: 11, color: "#5b6474" }}>
            No detector rules fired. Plan looks clean.
          </div>
        )}
        {problems.map((p, i) => {
          const c = chip(p.severity);
          const selected = selectedNode === i;
          return (
            <div
              key={i}
              onClick={() => onSelect(i)}
              onMouseEnter={() => onHoverRel(p.relation_name || null)}
              onMouseLeave={() => onHoverRel(null)}
              style={{
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
                padding: "8px 10px",
                borderRadius: 7,
                cursor: "pointer",
                background: selected ? "rgba(92,200,255,.06)" : "#0e1218",
                border: `1px solid ${selected ? "#2b3a4a" : "#151a22"}`,
              }}
              onMouseOver={(e) => {
                (e.currentTarget as HTMLDivElement).style.background = "#151a22";
              }}
              onMouseOut={(e) => {
                (e.currentTarget as HTMLDivElement).style.background = selected
                  ? "rgba(92,200,255,.06)"
                  : "#0e1218";
              }}
            >
              <div
                style={{
                  flex: "none",
                  marginTop: 1,
                  padding: "1px 6px",
                  borderRadius: 4,
                  fontSize: 9,
                  fontWeight: 700,
                  fontFamily: "'JetBrains Mono', monospace",
                  letterSpacing: ".05em",
                  color: c.fg,
                  background: c.bg,
                }}
              >
                {p.severity}
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 11.5, lineHeight: 1.5, color: "#e6eaf2" }}>{p.message}</div>
                <div
                  style={{
                    fontSize: 10,
                    fontFamily: "'JetBrains Mono', monospace",
                    color: "#5b6474",
                    marginTop: 2,
                  }}
                >
                  {p.type} · {p.node_type}
                  {p.relation_name ? ` · ${p.relation_name}` : ""}
                </div>
                {p.type === "STALE_STATISTICS" && (() => {
                  const cmd = extractAnalyzeCommand(p.message);
                  if (!cmd) return null;
                  const isCopied = copied === i;
                  return (
                    <div
                      style={{
                        marginTop: 6,
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "4px 8px",
                        background: "#0a0c10",
                        border: "1px solid #1c222c",
                        borderRadius: 5,
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: 10.5,
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <span style={{ color: "#c7cedb", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {cmd}
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          copyCmd(i, cmd);
                        }}
                        style={{
                          flex: "none",
                          padding: "2px 8px",
                          borderRadius: 3,
                          border: "1px solid #232a35",
                          background: "transparent",
                          color: isCopied ? "#3ecf8e" : "#8b94a7",
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: 9.5,
                          cursor: "pointer",
                        }}
                      >
                        {isCopied ? "copied" : "copy"}
                      </button>
                    </div>
                  );
                })()}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
