// Pre-reveal pipeline: LLM → validate → benchmark. Purely visual
// scaffolding around the real /optimize fetch — timers advance the
// visible stage while the request is in flight; the parent snaps
// stage=done when the promise resolves.

interface Step {
  label: string;
  detail: string;
  status: "pending" | "active" | "done";
}

interface Props {
  steps: Step[];
  onSkip?: () => void;
}

export function PipelineSteps({ steps, onSkip }: Props) {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 18,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10, width: 380 }}>
        {steps.map((s, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12,
              color: s.status === "pending" ? "#3a4152" : "#e6eaf2",
            }}
          >
            <div
              style={{
                width: 18,
                height: 18,
                flex: "none",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {s.status === "active" && (
                <div
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    border: "2px solid #232a35",
                    borderTopColor: "#ffb224",
                    animation: "odb-spin .7s linear infinite",
                  }}
                />
              )}
              {s.status === "done" && <span style={{ color: "#3ecf8e" }}>✓</span>}
              {s.status === "pending" && <span style={{ color: "#232a35" }}>·</span>}
            </div>
            <span>{s.label}</span>
            <div style={{ flex: 1 }} />
            <span style={{ color: "#5b6474", fontSize: 10 }}>{s.detail}</span>
          </div>
        ))}
      </div>
      {onSkip && (
        <button
          onClick={onSkip}
          style={{
            fontSize: 10,
            color: "#3a4152",
            cursor: "pointer",
            fontFamily: "'JetBrains Mono', monospace",
            background: "transparent",
            border: "none",
          }}
          onMouseOver={(e) => ((e.currentTarget as HTMLButtonElement).style.color = "#8b94a7")}
          onMouseOut={(e) => ((e.currentTarget as HTMLButtonElement).style.color = "#3a4152")}
        >
          skip →
        </button>
      )}
    </div>
  );
}
