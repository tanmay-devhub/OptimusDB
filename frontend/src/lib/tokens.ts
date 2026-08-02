// Design tokens — single source of truth, mirrored from the mockup's
// COLOR_TOKENS table. If you want a light theme later, split this into
// dark/light dicts and switch at the root.

export const bg = {
  base: "#0a0c10",
  panel: "#0c0f14",
  raised: "#151a22",
  hoverRow: "#0e1218",
  scrim: "rgba(6,8,11,.82)",
} as const;

export const border = {
  soft: "#151a22",
  mid: "#1c222c",
  strong: "#232a35",
  focus: "#2b3a4a",
  active: "#3a4557",
} as const;

export const text = {
  primary: "#e6eaf2",
  dim: "#8b94a7",
  faint: "#5b6474",
  ghost: "#3a4152",
  code: "#c7cedb",
} as const;

// Two accent tracks — amber is scarce (LLM/cost/spend), cyan is deterministic (free).
export const accent = {
  optimize: "#ffb224",
  optimizeDim: "rgba(255,178,36,.08)",
  analysis: "#5cc8ff",
  analysisDim: "rgba(92,200,255,.07)",
  analysisTint: "rgba(92,200,255,.14)",
} as const;

export const sev = {
  high: "#f4566a",
  highBg: "rgba(244,86,106,.14)",
  medium: "#d9a53d",
  mediumBg: "rgba(217,165,61,.13)",
  ok: "#3ecf8e",
  okBg: "rgba(62,207,142,.09)",
} as const;

export const font = {
  ui: "'Geist', ui-sans-serif, system-ui, -apple-system, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, 'Cascadia Code', Consolas, monospace",
} as const;
