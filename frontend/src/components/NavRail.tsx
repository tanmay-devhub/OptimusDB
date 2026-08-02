// 52px icon rail — brand logo, four view glyphs, reference sub-nav,
// and a pg connection health dot. Glyphs are Unicode, not an icon font.

import type { ViewId } from "../hooks/useShortcuts";

interface Props {
  view: ViewId;
  onView: (v: ViewId) => void;
  pgOk: boolean | null;
}

const NAV: [ViewId, string, string][] = [
  ["editor", "❯", "Editor  ⌘1"],
  ["workload", "≣", "Workload  ⌘2"],
  ["history", "↺", "History  ⌘3"],
  ["settings", "⚙", "Settings  ⌘4"],
];

function GlyphButton({
  active,
  title,
  glyph,
  onClick,
}: {
  active: boolean;
  title: string;
  glyph: string;
  onClick: () => void;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      className="w-9 h-9 rounded-lg flex items-center justify-center cursor-pointer transition-colors"
      style={{
        color: active ? "#e6eaf2" : "#5b6474",
        background: active ? "#151a22" : "transparent",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 16,
        border: "none",
      }}
      onMouseEnter={(e) => {
        if (!active) (e.currentTarget as HTMLButtonElement).style.background = "#151a22";
      }}
      onMouseLeave={(e) => {
        if (!active) (e.currentTarget as HTMLButtonElement).style.background = "transparent";
      }}
    >
      {glyph}
    </button>
  );
}

export function NavRail({ view, onView, pgOk }: Props) {
  const dotColor = pgOk === null ? "#5b6474" : pgOk ? "#3ecf8e" : "#f4566a";
  const dotGlow =
    pgOk === true ? "0 0 8px rgba(62,207,142,.6)" : pgOk === false ? "0 0 8px rgba(244,86,106,.5)" : "none";

  return (
    <div
      className="flex-none flex flex-col items-center border-r"
      style={{
        width: 52,
        borderColor: "#1c222c",
        background: "#0c0f14",
        padding: "10px 0",
        gap: 4,
      }}
    >
      <div
        title="OptimusDB"
        style={{
          width: 32,
          height: 32,
          borderRadius: 8,
          background: "linear-gradient(135deg,#ffb224,#e07800)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 700,
          fontSize: 15,
          color: "#0a0c10",
          marginBottom: 10,
        }}
      >
        Ø
      </div>

      {NAV.map(([id, glyph, title]) => (
        <GlyphButton
          key={id}
          active={view === id}
          title={title}
          glyph={glyph}
          onClick={() => onView(id)}
        />
      ))}

      <div style={{ flex: 1 }} />

      <GlyphButton
        active={view === "reference"}
        title="Design reference"
        glyph="¶"
        onClick={() => onView("reference")}
      />

      <div
        title={pgOk === true ? "postgres · connected" : pgOk === false ? "postgres · unreachable" : "postgres · checking"}
        style={{
          marginTop: 8,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 3,
        }}
      >
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: dotColor,
            boxShadow: dotGlow,
          }}
        />
        <div style={{ fontSize: 9, color: "#5b6474", fontFamily: "'JetBrains Mono', monospace" }}>pg16</div>
      </div>
    </div>
  );
}
