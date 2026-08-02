// Design reference — same visual language as the app, doubles as
// documentation. Shows the tokens, type scale, shortcuts, motion
// notes, and component inventory in one place.

const COLOR_TOKENS: { name: string; hex: string; why: string }[] = [
  { name: "bg/base", hex: "#0a0c10", why: "Near-black, blue-leaning. Editor canvas." },
  { name: "bg/panel", hex: "#0c0f14", why: "Panels & chrome, one step up." },
  { name: "bg/raised", hex: "#151a22", why: "Hover, active nav, chips." },
  { name: "border/1", hex: "#1c222c", why: "Structural dividers — elevation via borders, not shadows." },
  { name: "text/primary", hex: "#e6eaf2", why: "Cool white, never pure #fff." },
  { name: "text/dim", hex: "#8b94a7", why: "Secondary labels, metadata." },
  { name: "accent/optimize", hex: "#ffb224", why: "Amber = LLM actions & spend. Scarce by design: if it glows, it costs tokens." },
  { name: "accent/analysis", hex: "#5cc8ff", why: "Cyan = deterministic analysis, plan links, keywords. Free operations." },
  { name: "sev/high", hex: "#f4566a", why: "HIGH severity, bad estimates, regressions." },
  { name: "sev/medium", hex: "#d9a53d", why: "MEDIUM severity, seq scans." },
  { name: "ok", hex: "#3ecf8e", why: "Validated, faster, accepted." },
  { name: "text/faint", hex: "#5b6474", why: "Tertiary — units, hints, shortcuts." },
];

const TYPE_SCALE: { name: string; sample: string; size: string; weight: string; family: string }[] = [
  { name: "verdict", sample: "4.48×", size: "34px", weight: "700", family: "'JetBrains Mono', monospace" },
  { name: "view title", sample: "Workload", size: "13px", weight: "600", family: "'Geist', sans-serif" },
  { name: "body / ui", sample: "Accept rewrite", size: "12px", weight: "400", family: "'Geist', sans-serif" },
  { name: "code", sample: "SELECT count(*) FROM events;", size: "12.5px", weight: "400", family: "'JetBrains Mono', monospace" },
  { name: "data cell", sample: "1,943,208 → ×37", size: "11px", weight: "400", family: "'JetBrains Mono', monospace" },
  { name: "overline", sample: "PLAN TREE", size: "10px", weight: "500", family: "'JetBrains Mono', monospace" },
];

const SHORTCUTS: { keys: string; does: string }[] = [
  { keys: "⌘ ↩", does: "Analyze now (skip debounce)" },
  { keys: "⌘ ⇧ O", does: "Optimize with LLM" },
  { keys: "⌘ 1–5", does: "Switch view (editor / workload / history / settings / reference)" },
  { keys: "esc", does: "Close optimize overlay" },
  { keys: "click node", does: "Expand / collapse plan subtree" },
  { keys: "hover node", does: "Highlight table reference in SQL" },
];

const COMPONENTS: { name: string; props: string }[] = [
  { name: "SeverityChip", props: '{ severity: "HIGH"|"MEDIUM" } — mono 9px, tinted bg, never a solid fill' },
  { name: "ProblemCard", props: "{ problem, selected, onSelect, onHover } — links to plan node" },
  { name: "PlanNodeRow", props: "{ node, depth, collapsed, flagged, costPct, onToggle, onHover } — cost bar underlay" },
  { name: "SqlEditor", props: "{ value, onChange, highlightRel } — overlay textarea + tokenizer, 800ms debounce" },
  { name: "SqlText", props: "{ sql, highlight } — read-only highlighted SQL, used everywhere code appears" },
  { name: "ScanLoader", props: "{ width } — scan-line loading bar, deterministic ops only" },
  { name: "DiffPane", props: "{ diff } — line-tinted split diff over LCS" },
  { name: "BenchmarkStrip", props: "{ rows[], revealed } — dot distribution on log scale, staggered reveal" },
  { name: "PipelineSteps", props: "{ steps[], onSkip } — LLM → validate → benchmark progress" },
  { name: "NavRail", props: "{ view, onView, pgOk } — 52px icon rail, glyphs not icon-font" },
  { name: "Toast", props: "{ message } — bottom-center mono, fades up 8px on mount" },
];

const Overline = ({ children }: { children: React.ReactNode }) => (
  <div
    style={{
      fontSize: 10,
      fontFamily: "'JetBrains Mono', monospace",
      color: "#5b6474",
      textTransform: "uppercase",
      letterSpacing: ".08em",
      marginBottom: 10,
    }}
  >
    {children}
  </div>
);

export function ReferenceView() {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "auto" }}>
      <div
        style={{
          height: 44,
          flex: "none",
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "0 14px",
          borderBottom: "1px solid #1c222c",
          background: "#0c0f14",
        }}
      >
        <div style={{ fontWeight: 600 }}>Design reference</div>
        <div style={{ fontSize: 10, fontFamily: "'JetBrains Mono', monospace", color: "#5b6474" }}>
          tokens · type · components · motion · shortcuts
        </div>
      </div>

      <div
        style={{
          padding: "18px 14px 40px",
          display: "flex",
          flexDirection: "column",
          gap: 26,
          maxWidth: 900,
        }}
      >
        <div>
          <Overline>Color tokens</Overline>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: 8,
            }}
          >
            {COLOR_TOKENS.map((ct) => (
              <div
                key={ct.name}
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  padding: "8px 10px",
                  border: "1px solid #151a22",
                  borderRadius: 8,
                  background: "#0c0f14",
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 6,
                    flex: "none",
                    background: ct.hex,
                    border: "1px solid rgba(255,255,255,.08)",
                  }}
                />
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: 10.5,
                      color: "#e6eaf2",
                    }}
                  >
                    {ct.name} <span style={{ color: "#5b6474" }}>{ct.hex}</span>
                  </div>
                  <div style={{ fontSize: 10, color: "#8b94a7", lineHeight: 1.4 }}>{ct.why}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", gap: 26, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 280 }}>
            <Overline>Type scale — Geist / JetBrains Mono</Overline>
            <div
              style={{
                border: "1px solid #151a22",
                borderRadius: 8,
                background: "#0c0f14",
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 10.5,
              }}
            >
              {TYPE_SCALE.map((ts, i) => (
                <div
                  key={ts.name}
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 12,
                    padding: "7px 12px",
                    borderBottom: i === TYPE_SCALE.length - 1 ? "none" : "1px solid #12161d",
                  }}
                >
                  <span style={{ color: "#5b6474", width: 110, flex: "none" }}>{ts.name}</span>
                  <span
                    style={{
                      color: "#e6eaf2",
                      fontFamily: ts.family,
                      fontSize: ts.size,
                      fontWeight: ts.weight as unknown as number,
                    }}
                  >
                    {ts.sample}
                  </span>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 10, color: "#5b6474", marginTop: 8, lineHeight: 1.6 }}>
              Spacing: 4-px base grid (4/8/12/14 gutters). Radius: 4 chips · 6 buttons · 8 cards · 9
              panels. Elevation: borders over shadows — one shadow tier reserved for the optimize
              overlay.
            </div>
          </div>

          <div style={{ flex: 1, minWidth: 280 }}>
            <Overline>Keyboard shortcuts</Overline>
            <div
              style={{
                border: "1px solid #151a22",
                borderRadius: 8,
                background: "#0c0f14",
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
              }}
            >
              {SHORTCUTS.map((ks, i) => (
                <div
                  key={ks.keys}
                  style={{
                    display: "flex",
                    padding: "7px 12px",
                    borderBottom: i === SHORTCUTS.length - 1 ? "none" : "1px solid #12161d",
                  }}
                >
                  <span style={{ width: 110, flex: "none", color: "#ffb224" }}>{ks.keys}</span>
                  <span style={{ color: "#8b94a7" }}>{ks.does}</span>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 18 }}>
              <Overline>Motion notes</Overline>
              <div style={{ fontSize: 11, color: "#8b94a7", lineHeight: 1.7 }}>
                All chrome transitions ≤ 120ms ease-out. Debounce loading uses a scan-line, never a
                spinner. The <span style={{ color: "#e6eaf2" }}>signature moment</span> is the
                benchmark reveal: staged pipeline (LLM → validate → benchmark run counter) then
                verdict count-up (600ms) and latency dots cascading in with 25ms stagger — the
                pause is honest, it mirrors real work. Plan-tree hover cross-highlights the SQL
                fragment instantly (0ms in, 80ms out).
              </div>
            </div>
          </div>
        </div>

        <div>
          <Overline>Component inventory</Overline>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(270px, 1fr))",
              gap: 8,
            }}
          >
            {COMPONENTS.map((cp) => (
              <div
                key={cp.name}
                style={{
                  padding: "10px 12px",
                  border: "1px solid #151a22",
                  borderRadius: 8,
                  background: "#0c0f14",
                }}
              >
                <div
                  style={{
                    fontSize: 11.5,
                    fontWeight: 600,
                    color: "#5cc8ff",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  {cp.name}
                </div>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 10,
                    color: "#8b94a7",
                    marginTop: 4,
                    lineHeight: 1.6,
                  }}
                >
                  {cp.props}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
