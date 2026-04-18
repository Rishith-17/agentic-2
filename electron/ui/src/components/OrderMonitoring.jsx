import React, { useMemo } from "react";
import { ShoppingCart, ActivitySquare } from "lucide-react";
import StatusPill from "./StatusPill";

function extractOrderState(execution) {
  if (!execution?.result) return null;
  const result = execution.result;
  const plan = result.plan || {};
  const skillResult = result.skill_result || {};
  const routed = skillResult.result || {};
  const data = routed.data || {};

  const platform = data.platform || data.platform_used || null;
  const items =
    data.items ||
    data.search_results ||
    data.results ||
    (data.chosen_item ? [data.chosen_item] : []);

  return {
    task: execution.task,
    skill: plan.skill || result.skill_type,
    action: plan.action,
    platform,
    status: routed.success === false ? "error" : "active",
    checkoutStage: data.next_action || data.step || (data.order_id ? "order_created" : "pending"),
    message: routed.message || result.reply || "",
    items: Array.isArray(items) ? items : [],
  };
}

export default function OrderMonitoring({ latestExecution }) {
  const state = useMemo(() => extractOrderState(latestExecution), [latestExecution]);

  return (
    <section className="panel-shell space-y-4">
      <div className="panel-header">
        <div className="panel-title">
          <ShoppingCart size={16} /> Order Monitoring
        </div>
      </div>

      {!state ? (
        <div className="rounded-xl border border-cyan-500/20 bg-black/25 p-4 text-sm text-cyan-100/60">
          No active order context. Execute a task first.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <div className="metric-card">
              <div className="metric-label">Platform</div>
              <div className="metric-value">{state.platform || "—"}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Skill</div>
              <div className="metric-value">{state.skill || "—"}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Action</div>
              <div className="metric-value">{state.action || "—"}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Checkout Stage</div>
              <div className="metric-value">{state.checkoutStage || "pending"}</div>
            </div>
          </div>

          <div className="flex items-center justify-between rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3">
            <div className="inline-flex items-center gap-2 text-cyan-200">
              <ActivitySquare size={16} />
              <span className="text-sm">{state.message || "No status message"}</span>
            </div>
            <StatusPill label={state.status} state={state.status === "active" ? "ready" : "error"} />
          </div>

          <div className="max-h-[240px] space-y-2 overflow-y-auto pr-1">
            {state.items.map((item, idx) => (
              <div key={`${item.id || item.name || idx}-${idx}`} className="rounded-lg border border-cyan-500/20 bg-black/25 p-3">
                <div className="text-sm text-cyan-100">{item.name || `Item ${idx + 1}`}</div>
                <div className="mt-1 text-xs text-cyan-200/65">
                  Price: {item.price ?? "—"} {item.rating ? `| Rating: ${item.rating}` : ""}
                </div>
              </div>
            ))}
            {state.items.length === 0 ? <div className="text-sm text-cyan-100/60">No cart items parsed yet.</div> : null}
          </div>
        </>
      )}
    </section>
  );
}
