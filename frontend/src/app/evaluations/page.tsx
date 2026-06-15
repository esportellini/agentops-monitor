"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

interface Run {
  id: number; name: string; provider: string | null; model: string | null;
  status: string; pass_rate: number | null; average_score: number | null;
  total_cost: number | null; total_cases: number | null; created_at: string;
}
interface Dataset { id: number; name: string; version: string; created_at: string; }

const S: Record<string, string> = { COMPLETED: "text-status-ok", RUNNING: "text-brand-500", FAILED: "text-status-error", PENDING: "text-text-muted" };
const pct = (v: number | null) => v == null ? "—" : `${(v * 100).toFixed(1)}%`;
const usd = (v: number | null) => v == null ? "—" : `$${v.toFixed(4)}`;

export default function EvaluationsPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();

  const { data: runsData } = useQuery<{ items: Run[] }>({
    queryKey: ["eval-runs", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-runs?limit=10`),
    enabled: !!activeOrg,
  });
  const { data: dsData } = useQuery<{ items: Dataset[] }>({
    queryKey: ["eval-datasets", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-datasets`),
    enabled: !!activeOrg,
  });

  const runs = runsData?.items ?? [];
  const datasets = dsData?.items ?? [];

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Evaluations</h1>
            <p className="mt-1 text-sm text-text-secondary">Test and compare agent versions offline</p>
          </div>
          <div className="flex gap-3">
            <Link href="/evaluations/datasets" className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted transition-colors">Datasets</Link>
            <Link href="/evaluations/compare" className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 transition-colors">Compare runs</Link>
          </div>
        </div>

        <div className="mb-6 grid grid-cols-3 gap-4">
          {[["Datasets", datasets.length], ["Total runs", runs.length],
            ["Avg pass rate", runs.length === 0 ? "—" : pct(runs.reduce((s, r) => s + (r.pass_rate ?? 0), 0) / runs.length)]
          ].map(([label, val]) => (
            <div key={label as string} className="rounded-lg border border-surface-border bg-surface-card p-4">
              <p className="text-xs text-text-muted">{label}</p>
              <p className="mt-1 text-2xl font-bold text-text-primary">{val}</p>
            </div>
          ))}
        </div>

        <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-surface-border px-5 py-3">
            <h2 className="text-sm font-semibold text-text-primary">Recent runs</h2>
            <Link href="/evaluations/runs" className="text-xs text-brand-500 hover:underline">View all</Link>
          </div>
          <table className="w-full text-sm">
            <thead><tr className="border-b border-surface-border">
              {["Name", "Provider/Model", "Status", "Pass rate", "Score", "Cost", "Cases", "Date"].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider whitespace-nowrap">{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {runs.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-text-muted">
                  No runs yet. <Link href="/evaluations/runs" className="text-brand-500 hover:underline">Create one</Link>
                </td></tr>
              ) : runs.map(r => (
                <tr key={r.id} className="border-b border-surface-border last:border-0 hover:bg-surface-muted/30">
                  <td className="px-4 py-3"><Link href={`/evaluations/runs/${r.id}`} className="font-medium text-text-primary hover:text-brand-500">{r.name}</Link></td>
                  <td className="px-4 py-3 text-xs text-text-secondary">{[r.provider, r.model].filter(Boolean).join(" / ") || "—"}</td>
                  <td className="px-4 py-3"><span className={`text-xs font-medium ${S[r.status] ?? "text-text-muted"}`}>{r.status}</span></td>
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
