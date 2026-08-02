// App shell — routes the five views, owns SQL state and analysis
// state, threads /analyze debounce, /optimize orchestration, history
// persistence, keyboard shortcuts, and toast.

import { useCallback, useEffect, useRef, useState } from "react";
import { analyzeQuery, health, optimizeQuery } from "./api/client";
import type { AnalyzeResponse, OptimizeResponse } from "./api/types";
import { NavRail } from "./components/NavRail";
import { OptimizePanel } from "./components/OptimizePanel";
import { Toast } from "./components/Toast";
import { useDebounce } from "./hooks/useDebounce";
import { useShortcuts, type ViewId } from "./hooks/useShortcuts";
import { firstLine } from "./lib/format";
import {
  clearHistory,
  loadHistory,
  pushHistory,
  type HistoryEntry,
} from "./lib/history";
import { EditorView, type EditorState } from "./views/EditorView";
import { HistoryView } from "./views/HistoryView";
import { ReferenceView } from "./views/ReferenceView";
import { SettingsView } from "./views/SettingsView";
import { WorkloadView } from "./views/WorkloadView";

const DEFAULT_QUERY = `SELECT a.name,
       count(*)              AS events,
       count(DISTINCT s.id)  AS sessions
FROM events e
JOIN sessions s ON s.id = e.session_id
JOIN accounts a ON a.id = s.account_id
WHERE e.created_at >= now() - interval '7 days'
  AND e.name = 'feature_used'
GROUP BY a.name
ORDER BY events DESC
LIMIT 50;`;

export default function App() {
  const [view, setView] = useState<ViewId>("editor");
  const [sql, setSql] = useState(DEFAULT_QUERY);
  const debouncedSql = useDebounce(sql, 800);

  const [analyze, setAnalyze] = useState<AnalyzeResponse | null>(null);
  const [analyzeErr, setAnalyzeErr] = useState<string | null>(null);
  const [editorState, setEditorState] = useState<EditorState>("empty");

  const [optOpen, setOptOpen] = useState(false);
  const [optLoading, setOptLoading] = useState(false);
  const [optResult, setOptResult] = useState<OptimizeResponse | null>(null);
  const [optError, setOptError] = useState<string | null>(null);

  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [pgOk, setPgOk] = useState<boolean | null>(null);

  const [provider, setProvider] = useState<"groq" | "mistral" | "cerebras">("groq");
  const [temperature, setTemperature] = useState(0.1);

  const analyzeAbort = useRef<AbortController | null>(null);
  const toastTimer = useRef<number | null>(null);

  // Hydrate history + probe backend health once.
  useEffect(() => {
    setEntries(loadHistory());
    health()
      .then((h) => setPgOk(!!h.postgres))
      .catch(() => setPgOk(false));
  }, []);

  const fireToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2400);
  }, []);

  const runAnalyze = useCallback(
    (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || trimmed.split("\n").every((l) => !l.trim() || l.trim().startsWith("--"))) {
        setAnalyze(null);
        setAnalyzeErr(null);
        setEditorState("empty");
        return;
      }
      analyzeAbort.current?.abort();
      const ac = new AbortController();
      analyzeAbort.current = ac;
      setEditorState("loading");
      analyzeQuery(query, ac.signal)
        .then((r) => {
          setAnalyze(r);
          setAnalyzeErr(null);
          setEditorState("success");
          setEntries((prev) =>
            pushHistory(prev, {
              ts: Date.now(),
              kind: "ANALYZE",
              sql: firstLine(query),
              verdict: `${r.problems.length} problem${r.problems.length === 1 ? "" : "s"}`,
            }),
          );
        })
        .catch((e) => {
          if (e.name === "AbortError") return;
          setAnalyzeErr(String(e.message ?? e));
          setAnalyze(null);
          setEditorState("error");
        });
    },
    [],
  );

  // Debounced /analyze — the 800ms pause is the whole design goal here.
  useEffect(() => {
    runAnalyze(debouncedSql);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSql]);

  const runOptimize = useCallback(() => {
    if (!sql.trim()) return;
    setOptOpen(true);
    setOptLoading(true);
    setOptResult(null);
    setOptError(null);
    optimizeQuery(sql)
      .then((r) => {
        setOptResult(r);
      })
      .catch((e) => {
        setOptError(String(e.message ?? e));
      })
      .finally(() => setOptLoading(false));
  }, [sql]);

  useShortcuts({
    analyze: () => runAnalyze(sql),
    optimize: runOptimize,
    switchView: setView,
    closeOverlay: () => setOptOpen(false),
    overlayOpen: optOpen,
  });

  const onOpenInEditor = useCallback(
    (nextSql: string, mode: "analyze" | "paste") => {
      setSql(nextSql);
      setView("editor");
      if (mode === "paste") {
        fireToast("Replace $1, $2 … with concrete values, then ⌘↩");
        setEditorState("empty");
      } else {
        runAnalyze(nextSql);
      }
    },
    [fireToast, runAnalyze],
  );

  const onAcceptRewrite = useCallback(
    (nextSql: string) => {
      setSql(nextSql);
      setOptOpen(false);
      fireToast("Rewrite copied to editor — pasted back into query.sql");
    },
    [fireToast],
  );

  const onOptimizeResolved = useCallback(
    (accepted: boolean, speedup: number | null) => {
      setEntries((prev) =>
        pushHistory(prev, {
          ts: Date.now(),
          kind: "OPTIMIZE",
          sql: firstLine(sql),
          speedup,
          verdict: accepted ? "accepted" : "rejected",
        }),
      );
      if (!accepted) setOptOpen(false);
    },
    [sql],
  );

  return (
    <div style={{ position: "fixed", inset: 0, display: "flex", background: "#0a0c10", overflow: "hidden" }}>
      <NavRail view={view} onView={setView} pgOk={pgOk} />

      {view === "editor" && (
        <EditorView
          sql={sql}
          onSqlChange={setSql}
          state={editorState}
          analyze={analyze}
          errorText={analyzeErr}
          onAnalyzeNow={() => runAnalyze(sql)}
          onOptimize={runOptimize}
        />
      )}
      {view === "workload" && <WorkloadView onOpenInEditor={onOpenInEditor} />}
      {view === "history" && (
        <HistoryView
          entries={entries}
          onClear={() => {
            clearHistory();
            setEntries([]);
          }}
        />
      )}
      {view === "settings" && (
        <SettingsView
          provider={provider}
          onProvider={setProvider}
          temperature={temperature}
          onTemperature={setTemperature}
          pgOk={pgOk}
        />
      )}
      {view === "reference" && <ReferenceView />}

      <OptimizePanel
        open={optOpen}
        loading={optLoading}
        result={optResult}
        error={optError}
        onClose={() => setOptOpen(false)}
        onAccept={onAcceptRewrite}
        onReject={onOptimizeResolved}
      />

      <Toast message={toast} />
    </div>
  );
}
