import React from "react";

export default function StatusPill({ label, state = "unknown" }) {
  const normalized = String(state || "").toLowerCase();
  const tone =
    normalized === "ok" ||
    normalized === "ready" ||
    normalized === "true" ||
    normalized === "pass"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-400/40"
      : normalized === "warning" || normalized === "pending"
      ? "bg-amber-500/15 text-amber-300 border-amber-400/40"
      : "bg-rose-500/15 text-rose-300 border-rose-400/40";

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.16em] ${tone}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-90" />
      {label}
    </span>
  );
}
