import React, { useState } from "react";
import { Play, Loader2, Sparkles } from "lucide-react";
import { executeTask } from "../lib/api";

export default function TaskExecutionPanel({ onExecution }) {
  const [task, setTask] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [execution, setExecution] = useState(null);

  const runTask = async () => {
    if (!task.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await executeTask(task.trim(), "jarvis-dashboard");
      setExecution(res);
      onExecution?.(res);
      setTask("");
    } catch (e) {
      setError(e.message || "Task execution failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel-shell space-y-4">
      <div className="panel-header">
        <div className="panel-title">
          <Sparkles size={16} /> Task Execution Panel
        </div>
      </div>

      <div className="flex flex-col gap-3 md:flex-row">
        <input
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runTask()}
          placeholder="Order 2 pizzas from Domino's"
          className="flex-1 rounded-xl border border-cyan-500/30 bg-black/30 px-4 py-3 text-sm text-cyan-100 outline-none placeholder:text-cyan-500/45 focus:border-cyan-300"
        />
        <button
          onClick={runTask}
          disabled={busy}
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-300/40 bg-cyan-400/15 px-5 py-3 text-xs uppercase tracking-[0.18em] text-cyan-100 transition hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
          Execute
        </button>
      </div>

      {error ? <div className="rounded-lg border border-rose-500/40 bg-rose-500/15 p-3 text-sm text-rose-200">{error}</div> : null}

      <div className="space-y-2 rounded-xl border border-cyan-500/20 bg-black/25 p-3">
        <div className="text-xs uppercase tracking-[0.2em] text-cyan-300">Step-by-step execution logs</div>
        <div className="max-h-[240px] space-y-2 overflow-y-auto pr-1">
          {(execution?.steps || []).map((step, idx) => (
            <div key={`${step.phase}-${idx}`} className="rounded-lg border border-cyan-500/15 bg-cyan-500/5 p-2 text-xs">
              <div className="mb-1 flex items-center justify-between">
                <span className="font-mono text-cyan-100">{step.phase}</span>
                <span className={step.status === "ok" ? "text-emerald-300" : "text-rose-300"}>{step.status}</span>
              </div>
              <div className="text-cyan-200/70">
                {step.skill ? `${step.skill}.${step.action}` : "No skill action"}
                {step.error ? ` | error: ${step.error}` : ""}
              </div>
            </div>
          ))}
          {!execution ? <div className="text-sm text-cyan-100/55">No execution yet.</div> : null}
        </div>
      </div>
    </section>
  );
}
