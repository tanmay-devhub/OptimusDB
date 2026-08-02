// Compact number and duration formatting used by plan rows, workload cells,
// benchmark strips and history entries. Kept dependency-free.

export function fmtN(n: number): string {
  if (!Number.isFinite(n)) return "-";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e4) return Math.round(n / 1e3) + "k";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(Math.round(n));
}

export function fmtMs(v: number): string {
  if (!Number.isFinite(v)) return "-";
  if (v >= 1000) return (v / 1000).toFixed(1) + "s";
  if (v >= 100) return Math.round(v) + "ms";
  return v.toFixed(1) + "ms";
}

export function fmtDur(ms: number): string {
  if (!Number.isFinite(ms)) return "-";
  if (ms >= 3.6e6) return (ms / 3.6e6).toFixed(1) + "h";
  if (ms >= 6e4) return (ms / 6e4).toFixed(1) + "m";
  if (ms >= 1000) return (ms / 1000).toFixed(1) + "s";
  return Math.round(ms) + "ms";
}

export function firstLine(sql: string, max = 90): string {
  const s = (sql ?? "").replace(/\s+/g, " ").trim();
  return s.length > max ? s.slice(0, max) + "…" : s;
}

export function hhmm(ts: number): string {
  return new Date(ts).toTimeString().slice(0, 5);
}
