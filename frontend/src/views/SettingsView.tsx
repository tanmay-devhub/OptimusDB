// Settings — LLM provider picker, temperature slider, theme toggle
// placeholder, read-only Postgres connection details. Provider and
// temperature are local-only for now (the backend reads env vars);
// wiring them into /optimize is a small follow-up.

interface Props {
  provider: "groq" | "mistral" | "cerebras";
  onProvider: (p: "groq" | "mistral" | "cerebras") => void;
  temperature: number;
  onTemperature: (v: number) => void;
  pgOk: boolean | null;
}

const PROVIDERS: { id: "groq" | "mistral" | "cerebras"; name: string; model: string; meta: string }[] = [
  { id: "groq", name: "Groq", model: "llama-3.3-70b-versatile", meta: "~1.8s · $0.59/$0.79 per 1M tok" },
  { id: "mistral", name: "Mistral", model: "mistral-large-2411", meta: "~3.1s · $2.00/$6.00 per 1M tok" },
  { id: "cerebras", name: "Cerebras", model: "llama-3.3-70b", meta: "~0.9s · $0.85/$1.20 per 1M tok" },
];

export function SettingsView({ provider, onProvider, temperature, onTemperature, pgOk }: Props) {
  const pgConn = [
    { k: "backend", v: "http://localhost:8000/api", color: "#e6eaf2" },
    { k: "postgres reachable", v: pgOk === true ? "yes" : pgOk === false ? "no" : "checking", color: pgOk === true ? "#3ecf8e" : pgOk === false ? "#f4566a" : "#8b94a7" },
    { k: "pg_stat_statements", v: "expected · configured in postgres.conf", color: "#e6eaf2" },
    { k: "credentials", v: "read from project/.env (server-side)", color: "#8b94a7" },
  ];

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "auto" }}>
      <div
        style={{
          height: 44,
          flex: "none",
          display: "flex",
          alignItems: "center",
          padding: "0 14px",
          borderBottom: "1px solid #1c222c",
          background: "#0c0f14",
          fontWeight: 600,
        }}
      >
        Settings
      </div>
      <div style={{ padding: "18px 14px", display: "flex", flexDirection: "column", gap: 20, maxWidth: 760 }}>
        <div>
          <div
            style={{
              fontSize: 10,
              fontFamily: "'JetBrains Mono', monospace",
              color: "#5b6474",
              textTransform: "uppercase",
              letterSpacing: ".08em",
              marginBottom: 8,
            }}
          >
            LLM provider
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {PROVIDERS.map((p) => {
              const active = provider === p.id;
              return (
                <button
                  key={p.id}
                  onClick={() => onProvider(p.id)}
                  style={{
                    flex: 1,
                    padding: "12px 14px",
                    borderRadius: 9,
                    cursor: "pointer",
                    border: `1px solid ${active ? "#ffb224" : "#1c222c"}`,
                    background: active ? "rgba(255,178,36,.05)" : "#0c0f14",
                    textAlign: "left",
                  }}
                  onMouseOver={(e) => {
                    if (!active) (e.currentTarget as HTMLButtonElement).style.borderColor = "#3a4557";
                  }}
                  onMouseOut={(e) => {
                    if (!active) (e.currentTarget as HTMLButtonElement).style.borderColor = "#1c222c";
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ fontWeight: 600, fontSize: 12.5, color: "#e6eaf2" }}>{p.name}</div>
                    {active && (
                      <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#ffb224" }} />
                    )}
                  </div>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: 10,
                      color: "#8b94a7",
                      marginTop: 4,
                    }}
                  >
                    {p.model}
                  </div>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: 10,
                      color: "#5b6474",
                      marginTop: 6,
                    }}
                  >
                    {p.meta}
                  </div>
                </button>
              );
            })}
          </div>
          <div style={{ fontSize: 10.5, color: "#5b6474", marginTop: 8 }}>
            Provider is chosen server-side via <span style={{ color: "#8b94a7" }}>LLM_PROVIDER</span> in
            project/.env — this UI stores your preference locally; wiring it through /optimize is a
            follow-up.
          </div>
        </div>

        <div style={{ display: "flex", gap: 20 }}>
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: 10,
                fontFamily: "'JetBrains Mono', monospace",
                color: "#5b6474",
                textTransform: "uppercase",
                letterSpacing: ".08em",
                marginBottom: 8,
              }}
            >
              Temperature · {temperature.toFixed(2)}
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={temperature}
              onChange={(e) => onTemperature(parseFloat(e.target.value))}
              style={{ width: "100%" }}
            />
            <div style={{ fontSize: 10.5, color: "#5b6474", marginTop: 4 }}>
              Low = deterministic rewrites. Recommended ≤ 0.2 for SQL.
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: 10,
                fontFamily: "'JetBrains Mono', monospace",
                color: "#5b6474",
                textTransform: "uppercase",
                letterSpacing: ".08em",
                marginBottom: 8,
              }}
            >
              Theme
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <div
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: "1px solid #ffb224",
                  background: "rgba(255,178,36,.08)",
                  fontSize: 11,
                  color: "#e6eaf2",
                  whiteSpace: "nowrap",
                }}
              >
                Dark <span style={{ color: "#5b6474", fontSize: 10 }}>default</span>
              </div>
              <div
                title="not in MVP"
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: "1px solid #1c222c",
                  fontSize: 11,
                  color: "#3a4152",
                  cursor: "not-allowed",
                  whiteSpace: "nowrap",
                }}
              >
                Light
              </div>
            </div>
          </div>
        </div>

        <div>
          <div
            style={{
              fontSize: 10,
              fontFamily: "'JetBrains Mono', monospace",
              color: "#5b6474",
              textTransform: "uppercase",
              letterSpacing: ".08em",
              marginBottom: 8,
            }}
          >
            Connection <span style={{ color: "#3a4152" }}>read-only</span>
          </div>
          <div
            style={{
              border: "1px solid #1c222c",
              borderRadius: 9,
              background: "#0c0f14",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
            }}
          >
            {pgConn.map((pc, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  padding: "8px 14px",
                  borderBottom: i === pgConn.length - 1 ? "none" : "1px solid #12161d",
                }}
              >
                <div style={{ width: 200, color: "#5b6474" }}>{pc.k}</div>
                <div style={{ color: pc.color }}>{pc.v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
