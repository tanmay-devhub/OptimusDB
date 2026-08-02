import { useEffect, useState } from "react";

// Standard debounce hook. Delays updating a value until `ms` has passed
// without further changes. Used to avoid hammering /analyze on every keystroke.
export function useDebounce<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}
