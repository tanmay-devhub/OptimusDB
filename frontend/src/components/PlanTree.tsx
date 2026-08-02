// Plan tree — depth-indented rows with a cost-bar underlay, caret for
// collapsible subtrees, ratio flag when the planner is off by ≥10×.

import { useState } from "react";
import type { PlanNode } from "../api/types";
import { fmtN } from "../lib/format";
import { sev } from "../lib/tokens";

interface Props {
  nodes: PlanNode[];
  selectedNode: number | null;
  onSelect: (idx: number | null) => void;
  onHoverRel: (rel: string | null) => void;
}

export function PlanTree({ nodes, selectedNode, onSelect, onHoverRel }: Props) {
  const [collapsed, setCollapsed] = useState<Record<number, boolean>>({});

  const maxCost = Math.max(1, ...nodes.map((n) => n.total_cost));

  // Depth-first flatten respecting collapse — a subtree is hidden while
  // rows carry a strictly greater depth than the collapsed parent.
  const visible: { node: PlanNode; idx: number; hasKids: boolean }[] = [];
  let hideBelow = -1;
  nodes.forEach((n, idx) => {
    if (hideBelow >= 0) {
      if (n.depth > hideBelow) return;
      hideBelow = -1;
    }
    const next = nodes[idx + 1];
    const hasKids = !!next && next.depth > n.depth;
    visible.push({ node: n, idx, hasKids });
    if (collapsed[idx]) hideBelow = n.depth;
  });

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div
        style={{
          height: 30,
          flex: "none",
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
        Plan tree
        <div style={{ flex: 1 }} />
        <span style={{ textTransform: "none", letterSpacing: 0 }}>cost · rows est→act · loops</span>
      </div>
      <div className="scroll-y" style={{ flex: 1, overflow: "auto", padding: "0 8px 10px" }}>
        {visible.length === 0 && (
          <div style={{ padding: "6px 10px", fontSize: 11, color: "#5b6474" }}>
            No plan yet. Analysis will populate this pane.
          </div>
        )}
        {visible.map(({ node: n, idx, hasKids }) => {
          const ratio = n.actual_rows / Math.max(1, n.plan_rows);
          const flagged = ratio >= 10 || ratio <= 0.1;
          const selected = selectedNode === idx;
          const isSeq = /seq scan/i.test(n.node_type);
          const typeColor = isSeq ? sev.medium : "#c7cedb";
          const costPct = Math.round((100 * n.total_cost) / maxCost);
          const rowsColor = flagged ? sev.high : "#8b94a7";
          const ratioLabel = ratio >= 1 ? `×${Math.round(ratio)}` : `÷${Math.round(1 / ratio)}`;
          const caret = hasKids ? (collapsed[idx] ? "▸" : "▾") : "";
          const total = n.actual_loops > 1 ? n.actual_rows * n.actual_loops : n.actual_rows;

          return (
            <div
              key={idx}
              onClick={() => {
                if (hasKids) setCollapsed((c) => ({ ...c, [idx]: !c[idx] }));
                onSelect(idx);
              }}
              onMouseEnter={() => onHoverRel(n.relation_name || null)}
              onMouseLeave={() => onHoverRel(null)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: `4px 8px 4px ${8 + n.depth * 16}px`,
                borderRadius: 6,
                cursor: "pointer",
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                background: selected ? "rgba(92,200,255,.07)" : "transparent",
                border: `1px solid ${selected ? "#2b3a4a" : "transparent"}`,
                marginBottom: 2,
                position: "relative",
                overflow: "hidden",
              }}
              onMouseOver={(e) => {
                (e.currentTarget as HTMLDivElement).style.background = "#151a22";
              }}
              onMouseOut={(e) => {
                (e.currentTarget as HTMLDivElement).style.background = selected
                  ? "rgba(92,200,255,.07)"
                  : "transparent";
              }}
            >
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: `${costPct}%`,
                  background: "rgba(92,200,255,.05)",
                  pointerEvents: "none",
                }}
              />
              <span style={{ width: 10, flex: "none", color: "#5b6474", fontSize: 9 }}>{caret}</span>
              <span style={{ color: typeColor, fontWeight: 500, whiteSpace: "nowrap" }}>{n.node_type}</span>
              {n.relation_name && (
                <span style={{ color: "#5cc8ff", whiteSpace: "nowrap" }}>{n.relation_name}</span>
              )}
              {flagged && (
                <span
                  title="row estimate off by 10x+"
                  style={{
                    flex: "none",
                    padding: "0 5px",
                    borderRadius: 3,
                    background: "rgba(244,86,106,.15)",
                    color: sev.high,
                    fontSize: 9,
                    fontWeight: 700,
                  }}
                >
                  {ratioLabel}
                </span>
              )}
              <div style={{ flex: 1 }} />
              <span style={{ color: "#5b6474", whiteSpace: "nowrap", fontSize: 10 }}>
                {fmtN(n.total_cost)}
              </span>
              <span style={{ color: rowsColor, whiteSpace: "nowrap", fontSize: 10 }}>
                {fmtN(n.plan_rows)}→{fmtN(total)}
              </span>
              <span style={{ color: "#3a4152", whiteSpace: "nowrap", fontSize: 10 }}>×{n.actual_loops}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
