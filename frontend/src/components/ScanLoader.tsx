// Scan-line loader — deterministic operations only. Never a spinner
// (per the design brief: spinners are for spend, scans are for free work).

interface Props {
  width?: number;
}

export function ScanLoader({ width = 340 }: Props) {
  return (
    <div
      style={{
        width,
        height: 3,
        borderRadius: 2,
        background: "#151a22",
        overflow: "hidden",
        position: "relative",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 120,
          height: "100%",
          background: "linear-gradient(90deg,transparent,#5cc8ff,transparent)",
          animation: "odb-scan 1.1s linear infinite",
        }}
      />
    </div>
  );
}
