"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthFetch } from "@/hooks/useAuthFetch";

type Action = "detect" | "redact" | "alert" | "block";

interface AgentPolicy {
  id: number;
  agent_id: number;
  allowed_tools: string[] | null;
  blocked_tools: string[] | null;
  tools_requiring_approval: string[] | null;
  allowed_domains: string[] | null;
  blocked_domains: string[] | null;
  max_tokens_per_trace: number | null;
  max_cost_per_trace_usd: number | null;
  capture_inputs: boolean;
  capture_outputs: boolean;
  pii_action: Action;
  secret_action: Action;
  injection_action: Action;
  active: boolean;
}

const csv = (value: string) => Array.from(new Set(
  value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean),
));
const text = (value: string[] | null | undefined) => (value ?? []).join(", ");

export function AgentPolicyEditor({ orgId, agentId }: { orgId: number; agentId: number }) {
  const api = useAuthFetch();
  const qc = useQueryClient();
  const key = ["agent-policy", orgId, agentId];
  const { data, isLoading } = useQuery<{ items: AgentPolicy[] }>({
    queryKey: key,
    queryFn: () => api.get(`/api/v1/organizations/${orgId}/security/policies?agent_id=${agentId}`),
  });
  const policy = data?.items[0];
  const [form, setForm] = useState({
    allowed_tools: "", blocked_tools: "", tools_requiring_approval: "",
    allowed_domains: "", blocked_domains: "", max_tokens_per_trace: "",
    max_cost_per_trace_usd: "", capture_inputs: true, capture_outputs: true,
    pii_action: "alert" as Action, secret_action: "block" as Action,
    injection_action: "alert" as Action, active: true,
  });

  useEffect(() => {
    if (!policy) return;
    setForm({
      allowed_tools: text(policy.allowed_tools),
      blocked_tools: text(policy.blocked_tools),
      tools_requiring_approval: text(policy.tools_requiring_approval),
      allowed_domains: text(policy.allowed_domains),
      blocked_domains: text(policy.blocked_domains),
      max_tokens_per_trace: policy.max_tokens_per_trace?.toString() ?? "",
      max_cost_per_trace_usd: policy.max_cost_per_trace_usd?.toString() ?? "",
      capture_inputs: policy.capture_inputs, capture_outputs: policy.capture_outputs,
      pii_action: policy.pii_action, secret_action: policy.secret_action,
      injection_action: policy.injection_action, active: policy.active,
    });
  }, [policy]);

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        agent_id: agentId,
        allowed_tools: csv(form.allowed_tools), blocked_tools: csv(form.blocked_tools),
        tools_requiring_approval: csv(form.tools_requiring_approval),
        allowed_domains: csv(form.allowed_domains), blocked_domains: csv(form.blocked_domains),
        max_tokens_per_trace: form.max_tokens_per_trace === "" ? null : Number(form.max_tokens_per_trace),
        max_cost_per_trace_usd: form.max_cost_per_trace_usd === "" ? null : Number(form.max_cost_per_trace_usd),
        capture_inputs: form.capture_inputs, capture_outputs: form.capture_outputs,
        pii_action: form.pii_action, secret_action: form.secret_action,
        injection_action: form.injection_action, active: form.active,
      };
      const path = `/api/v1/organizations/${orgId}/security/policies${policy ? `/${policy.id}` : ""}`;
      return policy ? api.patch(path, payload) : api.post(path, payload);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  if (isLoading) return <div className="mt-6 text-sm text-text-muted">Loading policy…</div>;
  const set = <K extends keyof typeof form>(field: K, value: (typeof form)[K]) =>
    setForm((current) => ({ ...current, [field]: value }));
  const fieldClass = "mt-1 w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none";

  return (
    <section className="mt-6 rounded-lg border border-surface-border bg-surface-card p-5">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">Enforcement policy</h2>
          <p className="mt-1 text-xs text-text-muted">Tool preflight, trace budgets, capture, and security actions.</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-text-secondary">
          <input type="checkbox" checked={form.active} onChange={(e) => set("active", e.target.checked)} /> Active
        </label>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {([
          ["allowed_tools", "Allowed tools"], ["blocked_tools", "Blocked tools"],
          ["tools_requiring_approval", "Approval required"],
          ["allowed_domains", "Allowed domains"], ["blocked_domains", "Blocked domains"],
        ] as const).map(([field, label]) => (
          <label key={field} className="text-xs text-text-muted">{label} <span className="opacity-70">(comma separated)</span>
            <input className={fieldClass} value={form[field]} onChange={(e) => set(field, e.target.value)} />
          </label>
        ))}
        <label className="text-xs text-text-muted">Token limit per trace
          <input type="number" min="0" className={fieldClass} value={form.max_tokens_per_trace} onChange={(e) => set("max_tokens_per_trace", e.target.value)} />
        </label>
        <label className="text-xs text-text-muted">Cost limit per trace (USD)
          <input type="number" min="0" step="0.000001" className={fieldClass} value={form.max_cost_per_trace_usd} onChange={(e) => set("max_cost_per_trace_usd", e.target.value)} />
        </label>
        {(["pii_action", "secret_action", "injection_action"] as const).map((field) => (
          <label key={field} className="text-xs text-text-muted">{field.replace("_", " ")}
            <select className={fieldClass} value={form[field]} onChange={(e) => set(field, e.target.value as Action)}>
              {(["detect", "redact", "alert", "block"] as const).map((action) => <option key={action}>{action}</option>)}
            </select>
          </label>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-5">
        <label className="flex items-center gap-2 text-sm text-text-secondary"><input type="checkbox" checked={form.capture_inputs} onChange={(e) => set("capture_inputs", e.target.checked)} /> Capture inputs</label>
        <label className="flex items-center gap-2 text-sm text-text-secondary"><input type="checkbox" checked={form.capture_outputs} onChange={(e) => set("capture_outputs", e.target.checked)} /> Capture outputs</label>
        <button onClick={() => save.mutate()} disabled={save.isPending} className="ml-auto rounded-md bg-brand-500 px-4 py-2 text-sm text-white hover:bg-brand-600 disabled:opacity-50">
          {save.isPending ? "Saving…" : policy ? "Save policy" : "Create policy"}
        </button>
      </div>
      {save.isError && <p className="mt-3 text-xs text-status-error">Could not save this policy.</p>}
      {save.isSuccess && <p className="mt-3 text-xs text-status-ok">Policy saved.</p>}
    </section>
  );
}
