"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

interface Run { id: number; name: string; provider: string|null; model: string|null; status: string; pass_rate: number|null; average_score: number|null; total_cost: number|null; total_cases: number|null; dataset_id: number; created_at: string; }
interface Dataset { id: number; name: string; }

const S: Record<string,string> = { COMPLETED: "text-status-ok", RUNNING: "text-brand-500", FAILED: "text-status-error", PENDING: "text-text-muted" };
const pct = (v: number|null) => v==null ? "—" : `${(v*100).toFixed(1)}%`;
const usd = (v: number|null) => v==null ? "—" : `$${v.toFixed(4)}`;

export default function RunsPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [datasetId, setDatasetId] = useState("");
  const [runName, setRunName] = useState("Evaluation run");
  const [provider, setProvider] = useState("mock");
  const [running, setRunning] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const { data: runsData, isLoading } = useQuery<{ items: Run[] }>({
    queryKey: ["eval-runs", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-runs?limit=50`),
    enabled: !!activeOrg,
  });
  const { data: dsData } = useQuery<{ items: Dataset[] }>({
    queryKey: ["eval-datasets", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-datasets`),
    enabled: !!activeOrg,
  });

  async function handleRun() {
    if (!activeOrg || !datasetId) return;
    setRunning(true);
    try {
      await fetch.post(`/api/v1/organizations/${activeOrg.id}/evaluation-runs`, {
        dataset_id: parseInt(datasetId), name: runName, provider,
        config: { evaluators: [{ name: "json_structure", required_keys: [] }, { name: "cost_limit", max_cost_usd: 1.0 }] }
      });
      setShowForm(false);
      qc.invalidateQueries({ queryKey: ["eval-runs", activeOrg.id] });
    } finally { setRunning(false); }
  }

  const runs = runsData?.items ?? [];
  const datasets = dsData?.items ?? [];

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Evaluation Runs</h1>
            <p className="mt-1 text-sm text-text-secondary">Execute datasets against providers and models</p>
          </div>
          <div className="flex gap-3">
            <Link href="/evaluations/compare" className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted transition-colors">Compare</Link>
            <button onClick={() => setShowForm(!showForm)} className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 transition-colors">+ New run</button>
          </div>
        </div>

        {showForm && (
          <div className="mb-6 rounded-lg border border-surface-border bg-surface-card p-5 space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-text-muted mb-1">Run name</label>
                <input value={runName} onChange={e => setRunName(e.target.value)}
                  className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1">Dataset *</label>
                <select value={datasetId} onChange={e => setDatasetId(e.target.value)}
                  className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:outline-none">
                  <option value="">Select dataset…</option>
                  {datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1">Provider</label>
                <select value={provider} onChange={e => setProvider(e.target.value)}
                  className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:outline-none">
                  <option value="mock">mock (deterministic)</option>
                  <option value="openai" disabled>openai (coming soon)</option>
                  <option value="anthropic" disabled>anthropic (coming soon)</option>
                </select>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={handleRun} disabled={running || !datasetId}
                className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50 transition-colors">
                {running ? "Running…" : "Run evaluation"}
              </button>
              <button onClick={() => setShowForm(false)} className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted transition-colors">Cancel</button>
            </div>
          </div>
        )}

        <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-surface-border">
              {["Name", "Provider/Model", "Status", "Pass rate", "Score", "Cost", "Cases", "Date"].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider whitespace-nowrap">{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {isLoading ? <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-text-muted">Loading…</td></tr>
              : runs.length === 0 ? <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-text-muted">No runs yet.</td></tr>
              : runs.map(r => (
                <tr key={r.id} className="border-b border-surface-border last:border-0 hover:bg-surface-muted/30">
                  <td className="px-4 py-3"><Link href={`/evaluations/runs/${r.id}`} className="font-medium text-text-primary hover:text-brand-500">{r.name}</Link></td>
                  <td className="px-4 py-3 text-xs text-text-secondary">{[r.provider, r.model].filter(Boolean).join(" / ") || "—"}</td>
                  <td className="px-4 py-3"><span className={`text-xs font-medium ${S[r.status] ?? ""}`}>{r.status}</span></td>
                  <td className="px-4 py-3 tabular-nums text-text-primary">{pct(r.pass_rate)}</td>
                  <td className="px-4 py-3 tabular-nums text-text-secondary">{r.average_score != null ? r.average_score.toFixed(2) : "—"}</td>
                  <td className="px-4 py-3 tabular-nums text-text-secondary">{usd(r.total_cost)}</td>
                  <td className="px-4 py-3 tabular-nums text-text-secondary">{r.total_cases ?? "—"}</td>
                  <td className="px-4 py-3 text-xs text-text-muted">{new Date(r.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </ProtectedLayout>
  );
}
