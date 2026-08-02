// Bottom-center mono toast, fades up 8px on mount. Managed as a plain
// prop — parent decides when to clear it via setTimeout.

interface Props {
  message: string | null;
}

export function Toast({ message }: Props) {
  if (!message) return null;
  return (
    <div
      style={{
        position: "fixed",
        bottom: 20,
        left: "50%",
        transform: "translateX(-50%)",
        background: "#151a22",
        border: "1px solid #232a35",
        borderRadius: 8,
        padding: "9px 16px",
        fontSize: 11.5,
        color: "#e6eaf2",
        zIndex: 99,
        animation: "odb-fadeup .15s ease-out",
        boxShadow: "0 8px 30px rgba(0,0,0,.5)",
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {message}
    </div>
  );
}
