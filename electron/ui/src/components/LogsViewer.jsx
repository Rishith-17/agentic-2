import React from "react";
import { Bug, RefreshCw } from "lucide-react";

export default function LogsViewer({ logsData, loading, onRefresh }) {
  const logs = logsData?.logs || {};
  const preflightFailures = logsData?.preflight_critical_failures || [];

  return (
    <section className="panel-shell space-y-4">
      <div className="panel-header">
        <div className="panel-title">
          <Bug size={16} /> Error + Logs Viewer
        </div>
        <button
          onClick={onRefresh}
          className="inline-flex items-center gap-2 rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-3 py-1 text-[11px] uppercase tracking-[0.14em] text-cyan-100 hover:bg-cyan-400/20"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {preflightFailures.length > 0 ? (
        <div className="rounded-xl border border-amber-500/35 bg-amber-500/12 p-3">
          <div className="mb-2 text-xs uppercase tracking-[0.16em] text-amber-200">Preflight Failures</div>
          <div className="space-y-2">
            {preflightFailures.map((f, idx) => (
              <div key={`${f.name}-${idx}`} className="text-xs text-amber-100">
                <div className="font-mono">{f.name}</div>
                <div>{f.message}</div>
                {f.fix ? <div className="mt-1 text-amber-200/80">Fix: {f.fix}</div> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {Object.entries(logs).map(([name, content]) => (
          <div key={name} className="rounded-xl border border-cyan-500/20 bg-black/30 p-3">
            <div className="mb-2 text-xs uppercase tracking-[0.16em] text-cyan-200">{name}</div>
            <div className="h-[220px] overflow-y-auto rounded-lg border border-cyan-500/15 bg-black/40 p-2 font-mono text-[11px] text-cyan-100/80">
              {!content?.exists ? (
                <div className="text-cyan-100/45">Log file not found.</div>
              ) : content?.error ? (
                <div className="text-rose-300">Error: {content.error}</div>
              ) : (content?.lines || []).length === 0 ? (
                <div className="text-cyan-100/45">No log lines.</div>
              ) : (
                (content.lines || []).map((line, idx) => (
                  <div key={idx} className="whitespace-pre-wrap break-words">
                    {line}
                  </div>
                ))
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
