"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";

type Tab = "incidents" | "rules";

interface Agent { id: number; name: string; project_id: number }
interface Project { id: number; name: string }
interface Rule {
  id: number; name: string; description: string | null;
  event_type: string; condition: { metric: string; op: string; value: unknown };
  severity: string; status: string; project_id: number | null; agent_id: number | null;
}
interface Incident {
  id: number; rule_id: number; rule_name: string | null; event_type: string | null;
  source_type: string | null; source_id: string | null; trace_id: number | null;
  external_trace_id: string | null; project_id: number | null; agent_id: number | null;
  agent_name: string | null; severity: string; status: string; triggered_at: string;
  acknowledged_at: string | null; acknowledged_by_id: number | null;
  resolved_at: string | null; resolved_by_id: number | null;
  context: Record<string, unknown> | null; resolution_note: string | null;
}

const eventMetrics: Record<string, string[]> = {
  "security.finding.created": ["finding_type", "severity", "action_taken", "event_type"],
  "trace.finished": [
    "trace_status", "risk_level", "total_cost_usd", "total_tokens",
    "duration_ms", "unpriced_model_calls", "event_type",
  ],
};
const operators = ["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in"];
const severities = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

function emptyRule() {
  return {
    name: "", description: "", event_type: "security.finding.created",
    metric: "finding_type", op: "eq", value: "prompt_injection",
    severity: "HIGH", project_id: "", agent_id: "",
  };
}

export default function AlertsPage() {
  const { activeOrg } = useAuth();
  const api = useAuthFetch();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("incidents");
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [agentFilter, setAgentFilter] = useState("");
  const [selected, setSelected] = useState<Incident | null>(null);
  const [resolutionNote, setResolutionNote] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyRule());

  const base = `/api/v1/organizations/${activeOrg?.id}`;
  const incidentParams = new URLSearchParams({
    ...(status ? { status } : {}),
    ...(severity ? { severity } : {}),
    ...(agentFilter ? { agent_id: agentFilter } : {}),
  });
  const { data: incidents } = useQuery<{ items: Incident[] }>({
    queryKey: ["alert-incidents", activeOrg?.id, status, severity, agentFilter],
    queryFn: () => api.get(`${base}/alerts/incidents?${incidentParams}`),
    enabled: !!activeOrg,
  });
  const { data: rules } = useQuery<{ items: Rule[] }>({
    queryKey: ["alert-rules", activeOrg?.id],
    queryFn: () => api.get(`${base}/alerts/rules`),
    enabled: !!activeOrg,
  });
  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ["agents", activeOrg?.id],
    queryFn: () => api.get(`${base}/agents`),
    enabled: !!activeOrg,
  });
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ["projects", activeOrg?.id],
    queryFn: () => api.get(`${base}/projects`),
    enabled: !!activeOrg,
  });

  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["alert-incidents", activeOrg?.id] }),
      qc.invalidateQueries({ queryKey: ["alert-rules", activeOrg?.id] }),
    ]);
  };
  const transition = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "acknowledge" | "resolve" }) =>
      api.post<Incident>(
        `${base}/alerts/incidents/${id}/${action}`,
        action === "resolve" ? { note: resolutionNote || null } : undefined,
      ),
    onSuccess: async (incident) => { setSelected(incident); await refresh(); },
  });
  const saveRule = useMutation({
    mutationFn: async () => {
      const numeric = ["total_cost_usd", "total_tokens", "duration_ms", "unpriced_model_calls"]
        .includes(form.metric);
      const membership = ["in", "not_in"].includes(form.op);
      const members = form.value.split(",").map((item) => item.trim()).filter(Boolean);
      const rawValue = membership
        ? numeric ? members.map(Number) : members
        : numeric ? Number(form.value) : form.value;
      const payload = {
        name: form.name,
        description: form.description || null,
        event_type: form.event_type,
        condition: { metric: form.metric, op: form.op, value: rawValue },
        severity: form.severity,
        project_id: form.project_id ? Number(form.project_id) : null,
        agent_id: form.agent_id ? Number(form.agent_id) : null,
      };
      return editingId
        ? api.patch<Rule>(`${base}/alerts/rules/${editingId}`, payload)
        : api.post<Rule>(`${base}/alerts/rules`, payload);
    },
    onSuccess: async () => {
      setEditingId(null); setForm(emptyRule()); await refresh();
    },
  });
  const toggleRule = useMutation({
    mutationFn: (rule: Rule) => api.patch(
      `${base}/alerts/rules/${rule.id}`,
      { status: rule.status === "ACTIVE" ? "INACTIVE" : "ACTIVE" },
    ),
    onSuccess: refresh,
  });

  const submitRule = (event: FormEvent) => {
    event.preventDefault();
    saveRule.mutate();
  };
  const editRule = (rule: Rule) => {
    setEditingId(rule.id);
    setForm({
      name: rule.name,
      description: rule.description ?? "",
      event_type: rule.event_type,
      metric: rule.condition.metric,
      op: rule.condition.op,
      value: Array.isArray(rule.condition.value)
        ? rule.condition.value.join(", ") : String(rule.condition.value),
      severity: rule.severity,
      project_id: rule.project_id ? String(rule.project_id) : "",
      agent_id: rule.agent_id ? String(rule.agent_id) : "",
    });
    setTab("rules");
  };
  const scopedAgents = form.project_id
    ? agents.filter((agent) => agent.project_id === Number(form.project_id)) : agents;
  const availableOperators = ["total_cost_usd", "total_tokens", "duration_ms", "unpriced_model_calls"]
    .includes(form.metric) ? operators : operators.filter((item) => !["gt", "gte", "lt", "lte"].includes(item));

  return (
    <ProtectedLayout>
      <div className="p-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Alerts</h1>
          <p className="mt-1 text-sm text-text-muted">Runtime incidents from security findings and finished traces.</p>
        </div>
        <div className="mb-5 flex gap-2 border-b border-surface-border">
          {(["incidents", "rules"] as Tab[]).map((item) => (
            <button key={item} onClick={() => setTab(item)} className={`px-4 py-2 text-sm capitalize ${
              tab === item ? "border-b-2 border-brand-500 text-text-primary" : "text-text-muted"
            }`}>{item}</button>
          ))}
        </div>

        {tab === "incidents" ? (
          <>
            <div className="mb-4 flex flex-wrap gap-2">
              <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary">
                <option value="">All statuses</option><option>OPEN</option><option>ACKNOWLEDGED</option><option>RESOLVED</option>
              </select>
              <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary">
                <option value="">All severities</option>{severities.map((item) => <option key={item}>{item}</option>)}
              </select>
              <select value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary">
                <option value="">All agents</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
              </select>
            </div>
            <div className="overflow-hidden rounded-lg border border-surface-border bg-surface-card">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-surface-border bg-surface-muted text-xs text-text-muted"><tr>
                  <th className="px-4 py-3">Severity</th><th className="px-4 py-3">Rule</th>
                  <th className="px-4 py-3">Event</th><th className="px-4 py-3">Agent</th>
                  <th className="px-4 py-3">Triggered</th><th className="px-4 py-3">Status</th>
                </tr></thead>
                <tbody className="divide-y divide-surface-border">{incidents?.items.map((item) => (
                  <tr key={item.id} onClick={() => { setSelected(item); setResolutionNote(item.resolution_note ?? ""); }} className="cursor-pointer hover:bg-surface-muted/60">
                    <td className="px-4 py-3 font-medium text-text-primary">{item.severity}</td>
                    <td className="px-4 py-3 text-text-primary">{item.rule_name ?? `#${item.rule_id}`}</td>
                    <td className="px-4 py-3 font-mono text-xs text-text-muted">{item.event_type}</td>
                    <td className="px-4 py-3 text-text-secondary">{item.agent_name ?? "—"}</td>
                    <td className="px-4 py-3 text-text-muted">{new Date(item.triggered_at).toLocaleString()}</td>
                    <td className="px-4 py-3 text-text-secondary">{item.status}</td>
                  </tr>
                ))}</tbody>
              </table>
              {!incidents?.items.length && <p className="p-6 text-sm text-text-muted">No incidents match these filters.</p>}
            </div>
            {selected && (
              <section className="mt-5 rounded-lg border border-surface-border bg-surface-card p-5">
                <div className="flex items-start justify-between"><div>
                  <h2 className="font-medium text-text-primary">{selected.rule_name}</h2>
                  <p className="mt-1 font-mono text-xs text-text-muted">{selected.source_type} #{selected.source_id}</p>
                </div><button onClick={() => setSelected(null)} className="text-xs text-text-muted">Close</button></div>
                <div className="mt-4 flex gap-4 text-sm">
                  {selected.trace_id && <Link href={`/traces/${selected.trace_id}`} className="text-brand-500 hover:underline">Open trace</Link>}
                  {selected.source_type === "security_finding" && <Link href={`/security/findings/${selected.source_id}`} className="text-brand-500 hover:underline">Open finding</Link>}
                  {selected.agent_id && <Link href={`/agents/${selected.agent_id}`} className="text-brand-500 hover:underline">Open agent</Link>}
                </div>
                <pre className="mt-4 overflow-auto rounded bg-surface p-3 text-xs text-text-secondary">{JSON.stringify(selected.context ?? {}, null, 2)}</pre>
                {selected.status !== "RESOLVED" && <div className="mt-4">
                  <textarea value={resolutionNote} onChange={(e) => setResolutionNote(e.target.value)} maxLength={2000} placeholder="Resolution note" className="min-h-20 w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary" />
                  <div className="mt-2 flex justify-end gap-2">
                    {selected.status === "OPEN" && <button onClick={() => transition.mutate({ id: selected.id, action: "acknowledge" })} className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-primary">Acknowledge</button>}
                    <button onClick={() => transition.mutate({ id: selected.id, action: "resolve" })} className="rounded-md bg-brand-500 px-4 py-2 text-sm text-white">Resolve</button>
                  </div>
                </div>}
              </section>
            )}
          </>
        ) : (
          <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
            <div className="overflow-hidden rounded-lg border border-surface-border bg-surface-card">
              <table className="w-full text-left text-sm"><thead className="border-b border-surface-border bg-surface-muted text-xs text-text-muted"><tr>
                <th className="px-4 py-3">Rule</th><th className="px-4 py-3">Event</th><th className="px-4 py-3">Condition</th><th className="px-4 py-3">Severity</th><th className="px-4 py-3">Status</th><th className="px-4 py-3" />
              </tr></thead><tbody className="divide-y divide-surface-border">{rules?.items.map((rule) => (
                <tr key={rule.id}>
                  <td className="px-4 py-3 text-text-primary"><button onClick={() => editRule(rule)} className="hover:text-brand-500">{rule.name}</button></td>
                  <td className="px-4 py-3 font-mono text-xs text-text-muted">{rule.event_type}</td>
                  <td className="px-4 py-3 font-mono text-xs text-text-secondary">{rule.condition.metric} {rule.condition.op} {JSON.stringify(rule.condition.value)}</td>
                  <td className="px-4 py-3 text-text-secondary">{rule.severity}</td><td className="px-4 py-3 text-text-secondary">{rule.status}</td>
                  <td className="px-4 py-3"><button onClick={() => toggleRule.mutate(rule)} className="text-xs text-brand-500">{rule.status === "ACTIVE" ? "Deactivate" : "Activate"}</button></td>
                </tr>
              ))}</tbody></table>
            </div>
            <form onSubmit={submitRule} className="rounded-lg border border-surface-border bg-surface-card p-5">
              <h2 className="font-medium text-text-primary">{editingId ? "Edit rule" : "New rule"}</h2>
              <div className="mt-4 grid gap-3">
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Rule name" className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary" />
                <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Description" className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary" />
                <select value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value, metric: eventMetrics[e.target.value][0], op: "eq" })} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary">
                  {Object.keys(eventMetrics).map((item) => <option key={item}>{item}</option>)}
                </select>
                <div className="grid grid-cols-2 gap-2"><select value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value, op: "eq" })} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary">
                  {eventMetrics[form.event_type].map((item) => <option key={item}>{item}</option>)}
                </select><select value={form.op} onChange={(e) => setForm({ ...form, op: e.target.value })} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary">{availableOperators.map((item) => <option key={item}>{item}</option>)}</select></div>
                <input required value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} placeholder="Value; comma-separate for in" className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary" />
                <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary">{severities.map((item) => <option key={item}>{item}</option>)}</select>
                <select value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value, agent_id: "" })} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary"><option value="">All projects</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
                <select value={form.agent_id} onChange={(e) => setForm({ ...form, agent_id: e.target.value })} className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary"><option value="">All agents</option>{scopedAgents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
                <div className="flex justify-end gap-2">{editingId && <button type="button" onClick={() => { setEditingId(null); setForm(emptyRule()); }} className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-primary">Cancel</button>}<button disabled={saveRule.isPending} className="rounded-md bg-brand-500 px-4 py-2 text-sm text-white disabled:opacity-50">Save rule</button></div>
                {saveRule.isError && <p className="text-xs text-status-error">The rule is invalid or could not be saved.</p>}
              </div>
            </form>
          </div>
        )}
      </div>
    </ProtectedLayout>
  );
}
