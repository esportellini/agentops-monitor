"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";

interface Run { id: number; name: string; status: string; pass_rate: number|null; average_score: number|null; total_cost: number|null; average_latency_ms: number|null; total_cases: number|null; }
type RunSummary = { id:number; name:string; provider:string|null; model:string|null; pass_rate:number|null; average_score:number|null; total_cost:number|null; average_latency_ms:number|null; total_cases:number|null; passed_cases:number|null; error_cases:number|null; unpriced_cases:number|null; };
interface Comparison {
  run_a: RunSummary;
  run_b: RunSummary;
  shared_cases: number;
  improved_cases: number[];
  regressed_cases: number[];
  both_pass: number;
  both_fail: number;
  delta_pass_rate: number;
  delta_score: number;
  delta_cost: number;
  delta_latency_ms: number;
  cost_comparison_complete: boolean;
}

const pct = (v: number|null) => v==null ? "—" : `${(v*100).toFixed(1)}%`;
const usd = (v: number|null) => v==null ? "—" : `$${v.toFixed(4)}`;
const delta = (v: number, fmt: (n:number)=>string) => {
  const s = fmt(Math.abs(v));
  return v > 0 ? <span className="text-status-ok">+{s}</span> : v < 0 ? <span className="text-status-error">-{s}</span> : <span className="text-text-muted">±0</span>;
};

export default function ComparePage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const [runA, setRunA] = useState("");
  const [runB, setRunB] = useState("");

  const { data: runsData } = useQuery<{ items: Run[] }>({
    queryKey: ["eval-runs", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-runs?limit=100`),
    enabled: !!activeOrg,
  });

  const { data: comparison, isLoading: comparing, error } = useQuery<Comparison>({
    queryKey: ["eval-compare", runA, runB],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-runs/compare?run_a=${runA}&run_b=${runB}`),
    enabled: !!activeOrg && !!runA && !!runB && runA !== runB,
  });

  const runs = runsData?.items ?? [];

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-5xl">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Compare Runs</h1>
          <p className="mt-1 text-sm text-text-secondary">Side-by-side comparison of two evaluation runs</p>
        </div>

        <div className="mb-6 flex gap-4 items-end">
          {([["Run A (baseline)", runA, setRunA], ["Run B (challenger)", runB, setRunB]] as const).map(([label, val, set]) => (
            <div key={label as string} className="flex-1">
              <label className="block text-xs text-text-muted mb-1">{label}</label>
              <select value={val} onChange={e => set(e.target.value)}
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:outline-none">
                <option value="">Select run…</option>
                {runs.filter(r => r.status === "COMPLETED").map(r => (
                  <option key={r.id} value={r.id}>{r.name} ({pct(r.pass_rate)})</option>
                ))}
              </select>
            </div>
          ))}
        </div>

        {comparing && <div className="text-sm text-text-muted">Comparing…</div>}
        {error && <div className="text-sm text-status-error">Error loading comparison.</div>}
        {runA === runB && runA && <div className="text-sm text-yellow-400">Select two different runs.</div>}

        {comparison && (
          <div className="space-y-6">
            {/* Side-by-side metrics */}
            <div className="grid grid-cols-2 gap-4">
              {(["run_a", "run_b"] as const).map((key, ki) => {
                const r = comparison[key];
                return (
                  <div key={key} className={cn("rounded-lg border p-5", ki === 0 ? "border-surface-border bg-surface-card" : "border-brand-500/30 bg-brand-500/5")}>
                    <p className="mb-3 text-xs font-semibold uppercase text-text-muted">{ki === 0 ? "Run A (Baseline)" : "Run B (Challenger)"}</p>
                    <p className="text-base font-semibold text-text-primary mb-3">{r.name}</p>
                    <div className="space-y-2">
                      {([
                        ["Provider / Model", [r.provider, r.model].filter(Boolean).join(" / ") || "—"],
                        ["Pass rate", pct(r.pass_rate)],
                        ["Avg score", r.average_score != null ? r.average_score.toFixed(2) : "—"],
                        ["Known cost", usd(r.total_cost)],
                        ["Unpriced cases", String(r.unpriced_cases ?? 0)],
                        ["Provider errors", String(r.error_cases ?? 0)],
                        ["Avg latency", r.average_latency_ms != null ? `${r.average_latency_ms.toFixed(0)}ms` : "—"],
                        ["Cases", `${r.passed_cases ?? 0}/${r.total_cases ?? 0}`],
                      ] as [string, string][]).map(([lbl, val]) => (
                        <div key={lbl} className="flex justify-between text-sm">
                          <span className="text-text-muted">{lbl}</span>
                          <span className="font-medium text-text-primary tabular-nums">{val}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Delta summary */}
            <div className="rounded-lg border border-surface-border bg-surface-card p-5">
              <h2 className="mb-4 text-sm font-semibold text-text-primary">B vs A — Delta</h2>
              <div className="grid grid-cols-4 gap-4">
                {([
                  ["Pass rate", comparison.delta_pass_rate, (v: number) => pct(Math.abs(v))],
                  ["Score", comparison.delta_score, (v: number) => v.toFixed(2)],
                  ["Cost", comparison.delta_cost, (v: number) => usd(Math.abs(v))],
                  ["Latency", comparison.delta_latency_ms, (v: number) => `${Math.abs(v).toFixed(0)}ms`],
                ] as [string, number, (v:number)=>string][]).map(([label, val, fmt]) => (
                  <div key={label} className="text-center">
                    <p className="text-xs text-text-muted mb-1">{label}</p>
                    <p className="text-lg font-bold">{delta(val, fmt)}</p>
                  </div>
                ))}
              </div>
              {!comparison.cost_comparison_complete && <p className="mt-3 text-xs text-yellow-400">Cost comparison is incomplete because at least one run contains unpriced cases.</p>}
            </div>

            {/* Case outcomes */}
            <div className="grid grid-cols-4 gap-3">
              {([
                ["Improved cases", comparison.improved_cases.length, "text-status-ok border-status-ok/20 bg-status-ok/5"],
                ["Regressed cases", comparison.regressed_cases.length, "text-status-error border-status-error/20 bg-status-error/5"],
                ["Both pass", comparison.both_pass, "text-text-primary border-surface-border bg-surface-card"],
                ["Both fail", comparison.both_fail, "text-text-muted border-surface-border bg-surface-card"],
              ] as [string, number, string][]).map(([label, count, style]) => (
                <div key={label} className={cn("rounded-lg border p-4 text-center", style)}>
                  <p className="text-2xl font-bold">{count}</p>
                  <p className="text-xs mt-1 opacity-70">{label}</p>
                </div>
              ))}
            </div>

            {comparison.regressed_cases.length > 0 && (
              <div className="rounded-lg border border-status-error/20 bg-status-error/5 p-4">
                <p className="text-sm font-semibold text-status-error mb-2">Regressed case IDs</p>
                <p className="text-xs text-text-secondary">{comparison.regressed_cases.join(", ")}</p>
              </div>
            )}
            {comparison.improved_cases.length > 0 && (
              <div className="rounded-lg border border-status-ok/20 bg-status-ok/5 p-4">
                <p className="text-sm font-semibold text-status-ok mb-2">Improved case IDs</p>
                <p className="text-xs text-text-secondary">{comparison.improved_cases.join(", ")}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </ProtectedLayout>
  );
}
