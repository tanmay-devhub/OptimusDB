// Split diff pane — one line per row on each side, tinted red for
// removed and green for added. Line numbers hide (n=0) for the empty
// slots we insert to keep the two sides aligned.

import type { DiffPair } from "../lib/diff";
import { SqlText } from "../lib/sql";

interface Props {
  diff: DiffPair;
}

export function DiffPane({ diff }: Props) {
  return (
    <div style={{ flex: 1, display: "flex", minHeight: 0, overflow: "auto" }}>
      <div style={{ flex: 1, borderRight: "1px solid #151a22", padding: "10px 0" }}>
        {diff.left.map((d, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11.5,
              lineHeight: 1.65,
              background: d.mark === "del" ? "rgba(244,86,106,.09)" : "transparent",
              minHeight: "1.65em",
            }}
          >
            <span
              style={{
                width: 30,
                flex: "none",
                textAlign: "right",
                paddingRight: 10,
                color: "#3a4152",
                fontSize: 10,
                userSelect: "none",
              }}
            >
              {d.n || ""}
            </span>
            <span style={{ whiteSpace: "pre", paddingRight: 12 }}>
              <SqlText sql={d.text} />
            </span>
          </div>
        ))}
      </div>
      <div style={{ flex: 1, padding: "10px 0" }}>
        {diff.right.map((d, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11.5,
              lineHeight: 1.65,
              background: d.mark === "add" ? "rgba(62,207,142,.09)" : "transparent",
              minHeight: "1.65em",
            }}
          >
            <span
              style={{
                width: 30,
                flex: "none",
                textAlign: "right",
                paddingRight: 10,
                color: "#3a4152",
                fontSize: 10,
                userSelect: "none",
              }}
            >
              {d.n || ""}
            </span>
            <span style={{ whiteSpace: "pre", paddingRight: 12 }}>
              <SqlText sql={d.text} />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
