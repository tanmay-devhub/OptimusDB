// Session history persisted to localStorage. Survives refresh.
// Kept as a simple in-memory + storage round-trip; no reducer, no context.

export type HistoryKind = "ANALYZE" | "OPTIMIZE";
export type HistoryVerdict = "accepted" | "rejected" | string;

export interface HistoryEntry {
  ts: number;
  kind: HistoryKind;
  sql: string;
  speedup?: number | null;
  verdict?: HistoryVerdict;
}

const KEY = "optimusdb_history";
const MAX = 50;

export function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveHistory(entries: HistoryEntry[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(entries.slice(0, MAX)));
  } catch {
    // storage disabled — silently continue
  }
}

export function pushHistory(current: HistoryEntry[], entry: HistoryEntry): HistoryEntry[] {
  const next = [entry, ...current].slice(0, MAX);
  saveHistory(next);
  return next;
}

export function clearHistory(): void {
  try {
    localStorage.setItem(KEY, "[]");
  } catch {
    // ignore
  }
}
