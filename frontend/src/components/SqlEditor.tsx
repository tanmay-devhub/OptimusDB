// Editor pane — a transparent textarea overlaid on a syntax-highlighted
// <pre> renders the same text twice: the textarea holds caret + selection
// + input, the pre supplies color. Matches the mockup exactly; also fits
// our design tokens better than dropping a Monaco instance into a 12px
// mono panel would.

import { SqlText } from "../lib/sql";

interface Props {
  value: string;
  onChange: (next: string) => void;
  highlightRel?: string | null;
  placeholder?: string;
  onKeyboardMod?: () => void; // parent can hook analyzeNow etc. externally
}

export function SqlEditor({
  value,
  onChange,
  highlightRel = null,
  placeholder = "-- Paste a SQL query. Analysis fires 800ms after you stop typing.",
}: Props) {
  const lines = (value || "").split("\n");

  return (
    <div style={{ flex: 1, position: "relative", overflow: "auto", background: "#0a0c10" }}>
      <div style={{ display: "flex", minHeight: "100%" }}>
        <div
          style={{
            flex: "none",
            width: 44,
            padding: "12px 0",
            textAlign: "right",
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 12.5,
            lineHeight: 1.65,
            color: "#3a4152",
            userSelect: "none",
          }}
        >
          {lines.map((_, i) => (
            <div key={i} style={{ paddingRight: 14 }}>
              {i + 1}
            </div>
          ))}
        </div>
        <div style={{ flex: 1, position: "relative" }}>
          <pre
            style={{
              margin: 0,
              padding: "12px 16px 12px 0",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12.5,
              lineHeight: 1.65,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              minHeight: "100%",
            }}
          >
            <SqlText sql={value} highlight={highlightRel} />
          </pre>
          <textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            spellCheck={false}
            placeholder={placeholder}
            style={{
              position: "absolute",
              inset: 0,
              padding: "12px 16px 12px 0",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12.5,
              lineHeight: 1.65,
              background: "transparent",
              color: "transparent",
              caretColor: "#ffb224",
              border: "none",
              resize: "none",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              width: "100%",
              height: "100%",
            }}
          />
        </div>
      </div>
    </div>
  );
}
