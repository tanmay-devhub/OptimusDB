// Global keyboard shortcuts. Handlers are passed as an object so the
// caller can bind whatever they need without touching this hook.
//   ⌘ ↩       analyze now
//   ⌘ ⇧ O     optimize
//   ⌘ 1–5     switch view
//   esc       close overlay (if open)

import { useEffect } from "react";

export type ViewId = "editor" | "workload" | "history" | "settings" | "reference";

const VIEW_ORDER: ViewId[] = ["editor", "workload", "history", "settings", "reference"];

interface Handlers {
  analyze: () => void;
  optimize: () => void;
  switchView: (v: ViewId) => void;
  closeOverlay?: () => void;
  overlayOpen?: boolean;
}

export function useShortcuts(h: Handlers): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && h.overlayOpen) {
        h.closeOverlay?.();
        return;
      }
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      if (e.key === "Enter") {
        e.preventDefault();
        h.analyze();
      } else if (e.shiftKey && (e.key === "O" || e.key === "o")) {
        e.preventDefault();
        h.optimize();
      } else if (e.key >= "1" && e.key <= "5") {
        e.preventDefault();
        const idx = Number(e.key) - 1;
        h.switchView(VIEW_ORDER[idx]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [h]);
}
