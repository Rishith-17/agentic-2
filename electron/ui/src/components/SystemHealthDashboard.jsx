import React from "react";
import { Activity, Bot, ShieldCheck } from "lucide-react";
import StatusPill from "./StatusPill";

export default function SystemHealthDashboard({ health, loading, lastUpdated }) {
  const checks = health?.checks || [];
  const platforms = health?.platforms || {};

  return (
    <section className="space-y-4">
      <div className="panel-shell">
        <div className="panel-header">
          <div className="panel-title">
            <ShieldCheck size={16} /> System Health Dashboard
          </div>
          <StatusPill
            label={health?.automation_ready ? "Automation Ready" : "Automation Blocked"}
            state={health?.automation_ready ? "ready" : "error"}
          />
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="metric-card">
            <div className="metric-label">Browser Status</div>
            <div className="metric-value">{health?.browser_status || (loading ? "Loading..." : "Unknown")}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Preflight Checks</div>
            <div className="metric-value">
              {checks.filter((c) => c.ok).length}/{checks.length || 0} pass
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Last Update</div>
            <div className="metric-value">{lastUpdated || "—"}</div>
          </div>
        </div>
      </div>

      <div className="panel-shell">
        <div className="panel-header">
          <div className="panel-title">
            <Bot size={16} /> Platform Readiness
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {Object.entries(platforms).map(([name, info]) => (
            <div key={name} className="rounded-xl border border-cyan-500/20 bg-black/25 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm uppercase tracking-[0.18em] text-cyan-200">{name}</span>
                <StatusPill label={info?.ready ? "Ready" : "Not Ready"} state={info?.ready ? "ready" : "error"} />
              </div>
              <div className="text-xs text-cyan-100/70">{info?.reason || "No details"}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel-shell">
        <div className="panel-header">
          <div className="panel-title">
            <Activity size={16} /> Preflight Checks
          </div>
        </div>
        <div className="max-h-[260px] space-y-2 overflow-y-auto pr-1">
          {checks.map((check) => (
            <div key={check.name} className="rounded-xl border border-cyan-500/15 bg-cyan-500/5 p-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="font-mono text-[12px] text-cyan-200">{check.name}</span>
                <StatusPill label={check.ok ? "PASS" : "FAIL"} state={check.ok ? "pass" : "error"} />
              </div>
              <div className="text-xs text-cyan-100/70">{check.message}</div>
              {!check.ok && check.fix ? (
                <div className="mt-2 rounded-md border border-amber-500/35 bg-amber-500/10 p-2 text-[11px] text-amber-200">
                  Fix: {check.fix}
                </div>
              ) : null}
            </div>
          ))}
          {checks.length === 0 ? <div className="text-sm text-cyan-200/60">No checks yet.</div> : null}
        </div>
      </div>
    </section>
  );
}
