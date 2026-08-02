// Editor view — SQL pane on the left, analysis pane on the right.
// Debounced /analyze fires 800ms after the user pauses. LLM never
// fires here; that's the /optimize path (⌘⇧O or Optimize button).

import { useState } from "react";
import type { AnalyzeResponse } from "../api/types";
import { PlanTree } from "../components/PlanTree";
import { ProblemsList } from "../components/ProblemsList";
import { ScanLoader } from "../components/ScanLoader";
import { SqlEditor } from "../components/SqlEditor";

export type EditorState = "empty" | "loading" | "error" | "success";

interface SampleChip {
  label: string;
  sql: string;
}

const SAMPLES: SampleChip[] = [
  {
    label: "top accounts",
    sql: `SELECT a.name,
       count(*)              AS events,
       count(DISTINCT s.id)  AS sessions
FROM events e
JOIN sessions s ON s.id = e.session_id
JOIN accounts a ON a.id = s.account_id
WHERE e.created_at >= now() - interval '7 days'
  AND e.name = 'feature_used'
GROUP BY a.name
ORDER BY events DESC
LIMIT 50;`,
  },
  {
    label: "dau 30d",
    sql: `SELECT date_trunc('day', created_at) AS day,
       count(DISTINCT user_id)       AS dau
FROM events
WHERE created_at >= now() - interval '30 days'
GROUP BY 1
ORDER BY 1;`,
  },
  {
    label: "bad sql",
    sql: `SELECT a.name, count(*)
FORM events e
WHERE e.name = 'feature_used'
GROUP BY a.name;`,
  },
];

interface Props {
  sql: string;
  onSqlChange: (next: string) => void;
  state: EditorState;
  analyze: AnalyzeResponse | null;
  errorText: string | null;
  onAnalyzeNow: () => void;
  onOptimize: () => void;
}

export function EditorView({
  sql,
  onSqlChange,
  state,
  analyze,
  errorText,
  onAnalyzeNow,
  onOptimize,
}: Props) {
  const [hoverRel, setHoverRel] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<number | null>(null);

  const planningMs = analyze ? `${analyze.planning_ms.toFixed(2)}ms` : "-";
  const executionMs = analyze ? `${analyze.execution_ms.toFixed(1)}ms` : "-";
  const problemCount = analyze?.problems.length ?? 0;

  const statusLine =
    state === "loading"
      ? "analyzing…"
      : state === "error"
        ? "error"
        : state === "success"
          ? `analyzed · ${problemCount} problems · 0 tokens spent`
          : "idle";

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
        <div style={{ fontWeight: 600, fontSize: 13 }}>Editor</div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: "#8b94a7",
          }}
        >
          <span style={{ color: "#5b6474" }}>plan</span>
          <span style={{ color: "#e6eaf2" }}>{planningMs}</span>
          <span style={{ color: "#5b6474", marginLeft: 8 }}>exec</span>
          <span style={{ color: "#e6eaf2" }}>{executionMs}</span>
        </div>

        <div style={{ flex: 1 }} />

        <button
          onClick={onAnalyzeNow}
          style={{
            padding: "5px 10px",
            borderRadius: 6,
            border: "1px solid #232a35",
            color: "#8b94a7",
            fontSize: 11,
            cursor: "pointer",
            display: "flex",
            gap: 6,
            alignItems: "center",
            whiteSpace: "nowrap",
            background: "transparent",
          }}
          onMouseOver={(e) => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "#3a4557";
            (e.currentTarget as HTMLButtonElement).style.color = "#e6eaf2";
          }}
          onMouseOut={(e) => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "#232a35";
            (e.currentTarget as HTMLButtonElement).style.color = "#8b94a7";
          }}
        >
          Analyze <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#5b6474" }}>⌘↩</span>
        </button>
        <button
          onClick={onOptimize}
          disabled={!sql.trim()}
          style={{
            padding: "5px 12px",
            borderRadius: 6,
            background: "#ffb224",
            color: "#0a0c10",
            fontWeight: 600,
            fontSize: 11,
            cursor: sql.trim() ? "pointer" : "not-allowed",
            display: "flex",
            gap: 6,
            alignItems: "center",
            whiteSpace: "nowrap",
            border: "none",
            opacity: sql.trim() ? 1 : 0.5,
          }}
          onMouseOver={(e) => {
            if (sql.trim()) (e.currentTarget as HTMLButtonElement).style.filter = "brightness(1.1)";
          }}
          onMouseOut={(e) => ((e.currentTarget as HTMLButtonElement).style.filter = "none")}
        >
          Optimize with LLM <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, opacity: 0.6 }}>⌘⇧O</span>
        </button>
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <div
          style={{
            flex: 1.2,
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            borderRight: "1px solid #1c222c",
          }}
        >
          <div
            style={{
              height: 30,
              flex: "none",
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "0 12px",
              borderBottom: "1px solid #151a22",
              background: "#0b0e12",
            }}
          >
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#5b6474" }}>
              query.sql
            </span>
            <div style={{ flex: 1 }} />
            {SAMPLES.map((s) => (
              <button
                key={s.label}
                onClick={() => onSqlChange(s.sql)}
                style={{
                  fontSize: 10,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: "#8b94a7",
                  padding: "2px 7px",
                  borderRadius: 4,
                  border: "1px solid #1c222c",
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  background: "transparent",
                }}
                onMouseOver={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color = "#5cc8ff";
                  (e.currentTarget as HTMLButtonElement).style.borderColor = "#2b3a4a";
                }}
                onMouseOut={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color = "#8b94a7";
                  (e.currentTarget as HTMLButtonElement).style.borderColor = "#1c222c";
                }}
              >
                {s.label}
              </button>
            ))}
          </div>

          <SqlEditor value={sql} onChange={onSqlChange} highlightRel={hoverRel} />

          <div
            style={{
              height: 26,
              flex: "none",
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "0 12px",
              borderTop: "1px solid #151a22",
              background: "#0b0e12",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              color: "#5b6474",
            }}
          >
            <span>{statusLine}</span>
            <div style={{ flex: 1 }} />
            <span>postgres · localhost:5432</span>
          </div>
        </div>

        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            maxWidth: 560,
            background: "#0c0f14",
          }}
        >
          {state === "empty" && (
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 12,
                color: "#5b6474",
                padding: 32,
              }}
            >
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 26, color: "#232a35" }}>
                EXPLAIN
              </div>
              <div style={{ fontSize: 12, textAlign: "center", maxWidth: 280, lineHeight: 1.6 }}>
                Type or paste a query. The analyzer runs{" "}
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#8b94a7" }}>
                  EXPLAIN&nbsp;ANALYZE
                </span>{" "}
                automatically when you pause — no LLM tokens spent.
              </div>
              <div style={{ fontSize: 10, fontFamily: "'JetBrains Mono', monospace", color: "#3a4152" }}>
                ⌘↩ analyze now · ⌘⇧O optimize · ⌘1–5 views
              </div>
            </div>
          )}

          {state === "loading" && (
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 14,
                color: "#8b94a7",
              }}
            >
              <ScanLoader />
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
                EXPLAIN (ANALYZE, FORMAT JSON) …
              </div>
              <div style={{ fontSize: 10, color: "#5b6474" }}>deterministic · no tokens spent</div>
            </div>
          )}

          {state === "error" && (
            <div style={{ flex: 1, padding: 20, display: "flex", flexDirection: "column", gap: 10 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  color: "#f4566a",
                  fontWeight: 600,
                  fontSize: 12,
                }}
              >
                <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>✕</span>
                Analysis failed
              </div>
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11.5,
                  lineHeight: 1.7,
                  color: "#e6eaf2",
                  background: "#12080b",
                  border: "1px solid #3a1620",
                  borderRadius: 8,
                  padding: "12px 14px",
                  whiteSpace: "pre-wrap",
                }}
              >
                {errorText || "unknown error"}
              </div>
              <div style={{ fontSize: 11, color: "#5b6474" }}>
                Fix the statement — analysis re-fires when you pause typing.
              </div>
            </div>
          )}

          {state === "success" && analyze && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
              <ProblemsList
                problems={analyze.problems}
                selectedNode={selectedNode}
                onSelect={setSelectedNode}
                onHoverRel={setHoverRel}
              />
              <PlanTree
                nodes={analyze.plan_nodes}
                selectedNode={selectedNode}
                onSelect={setSelectedNode}
                onHoverRel={setHoverRel}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
