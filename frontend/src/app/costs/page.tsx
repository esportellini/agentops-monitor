"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

interface CostSummary {
  period: { since: string; until: string };
  total_cost_usd: number;
  total_executions: number;
  unpriced_model_calls: number;
  avg_cost_per_execution_usd: number;
  monthly_projection_usd: number;
  cost_by_model: { provider: string; model: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number; unpriced_calls: number }[];
  top_expensive_traces: { id: number; external_trace_id: string; name: string; status: string; started_at: string; duration_ms: number | null; total_cost_usd: number; total_tokens: number; unpriced_model_calls: number }[];
}

interface Projection {
  daily_avg_usd: number;
  mtd_cost_usd: number;
  projected_month_total_usd: number;
  projected_remaining_usd: number;
  days_elapsed: number;
  days_remaining: number;
}

const PERIODS = [
  { label: "Today", days: 1 },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

function fmtCost(n: number) {
  if (n === 0) return "$0.00";
  if (n < 0.0001) return `$${n.toFixed(8)}`;
  if (n < 0.01) return `$${n.toFixed(6)}`;
  if (n < 1) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmtTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtMs(ms: number | null) {
  if (!ms) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export default function CostsPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const [days, setDays] = useState(30);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");

  const base = `/api/v1/organizations/${activeOrg?.id}`;

  const until = new Date().toISOString();
  const since = new Date(Date.now() - days * 86400_000).toISOString();

  const params = new URLSearchParams({ since, until });
  if (provider) params.set("provider", provider);
  if (model) params.set("model", model);

  const { data: summary, isLoading } = useQuery<CostSummary>({
    queryKey: ["costs", activeOrg?.id, days, provider, model],
    queryFn: () => fetch.get(`${base}/costs?${params}`),
    enabled: !!activeOrg,
  });

  const { data: projection } = useQuery<Projection>({
    queryKey: ["cost-projection", activeOrg?.id],
    queryFn: () => fetch.get(`${base}/costs/projection`),
    enabled: !!activeOrg,
  });

  return (
    <ProtectedLayout>
      <div className="p-8 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Costs</h1>
            <p className="mt-1 text-sm text-text-secondary">Track and analyze your AI spend</p>
          </div>
        </div>

        {!!summary?.unpriced_model_calls && (
          <div className="flex items-center gap-2 rounded-lg border border-status-warn/30 bg-status-warn/10 px-4 py-3 text-sm text-text-secondary">
            <span className="rounded-full bg-status-warn/20 px-2 py-0.5 text-xs font-medium text-status-warn">Unpriced</span>
            {summary.unpriced_model_calls.toLocaleString()} model {summary.unpriced_model_calls === 1 ? "call has" : "calls have"} no configured price. Totals include known costs only.
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex gap-1 rounded-lg border border-surface-border bg-surface p-1">
            {PERIODS.map((p) => (
              <button
                key={p.days}
                onClick={() => setDays(p.days)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  days === p.days
                    ? "bg-brand-500 text-white"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <input
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            placeholder="Provider (e.g. openai)"
            className="rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-text-primary focus:border-brand-500 focus:outline-none w-40"
          />
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="Model (e.g. gpt-4o)"
            className="rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-text-primary focus:border-brand-500 focus:outline-none w-44"
          />
          {(provider || model) && (
            <button
              onClick={() => { setProvider(""); setModel(""); }}
              className="text-xs text-text-muted hover:text-text-secondary"
            >
              Clear
            </button>
          )}
        </div>

        {/* Top KPIs */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            ["Total cost", fmtCost(summary?.total_cost_usd ?? 0)],
            ["Executions", (summary?.total_executions ?? 0).toLocaleString()],
            ["Cost / execution", fmtCost(summary?.avg_cost_per_execution_usd ?? 0)],
            ["Monthly projection", fmtCost(summary?.monthly_projection_usd ?? 0)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-surface-border bg-surface-card p-4">
              <p className="text-xs text-text-muted">{label}</p>
              <p className="mt-1 text-xl font-semibold text-text-primary tabular-nums">{value}</p>
            </div>
          ))}
        </div>

        {/* Projection card */}
        {projection && (
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Monthly projection</h2>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 text-sm">
              <div>
                <p className="text-xs text-text-muted">Daily average</p>
                <p className="mt-0.5 font-medium text-text-primary tabular-nums">{fmtCost(projection.daily_avg_usd)}</p>
              </div>
              <div>
                <p className="text-xs text-text-muted">Month-to-date</p>
                <p className="mt-0.5 font-medium text-text-primary tabular-nums">{fmtCost(projection.mtd_cost_usd)}</p>
              </div>
              <div>
                <p className="text-xs text-text-muted">Remaining ({projection.days_remaining}d)</p>
                <p className="mt-0.5 font-medium text-text-primary tabular-nums">{fmtCost(projection.projected_remaining_usd)}</p>
              </div>
              <div>
                <p className="text-xs text-text-muted">Projected total</p>
                <p className="mt-0.5 font-semibold text-brand-500 tabular-nums">{fmtCost(projection.projected_month_total_usd)}</p>
              </div>
            </div>
          </div>
        )}

        {/* Cost by model */}
        <div className="rounded-lg border border-surface-border bg-surface-card p-5">
          <h2 className="mb-4 text-sm font-semibold text-text-primary">Cost by model</h2>
          {!summary?.cost_by_model?.length ? (
            <p className="text-sm text-text-muted">No data for this period.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border">
                  {["Provider", "Model", "Calls", "Input tokens", "Output tokens", "Cost"].map((h) => (
                    <th key={h} className="pb-2 text-left text-xs font-medium text-text-muted">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {summary.cost_by_model.map((r, i) => (
                  <tr key={i} className="border-b border-surface-border/50 last:border-0">
                    <td className="py-2 text-text-secondary">{r.provider}</td>
                    <td className="py-2 font-mono text-xs text-text-primary">{r.model}</td>
                    <td className="py-2 text-text-muted tabular-nums">{r.calls.toLocaleString()}</td>
                    <td className="py-2 text-text-muted tabular-nums">{fmtTokens(r.input_tokens)}</td>
                    <td className="py-2 text-text-muted tabular-nums">{fmtTokens(r.output_tokens)}</td>
                    <td className="py-2 font-medium text-text-primary tabular-nums">
                      {r.unpriced_calls === r.calls ? (
                        <span className="rounded-full bg-status-warn/15 px-2 py-0.5 text-xs text-status-warn">Unpriced</span>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span>{fmtCost(r.cost_usd)}</span>
                          {r.unpriced_calls > 0 && (
                            <span className="rounded-full bg-status-warn/15 px-2 py-0.5 text-xs text-status-warn">
                              {r.unpriced_calls} unpriced
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Top expensive traces */}
        <div className="rounded-lg border border-surface-border bg-surface-card p-5">
          <h2 className="mb-4 text-sm font-semibold text-text-primary">Most expensive traces</h2>
          {!summary?.top_expensive_traces?.length ? (
            <p className="text-sm text-text-muted">No traces found.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border">
                  {["Trace", "Status", "Started", "Duration", "Tokens", "Cost"].map((h) => (
                    <th key={h} className="pb-2 text-left text-xs font-medium text-text-muted">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {summary.top_expensive_traces.map((t) => (
                  <tr key={t.id} className="border-b border-surface-border/50 last:border-0 hover:bg-surface-muted/30 transition-colors">
                    <td className="py-2">
                      <Link href={`/traces/${t.id}`} className="text-brand-500 hover:underline font-mono text-xs">
                        {t.external_trace_id ?? `#${t.id}`}
                      </Link>
                      <p className="text-text-muted text-xs truncate max-w-xs">{t.name}</p>
                    </td>
                    <td className="py-2">
                      <span className={`text-xs font-medium ${t.status === "SUCCESS" ? "text-status-ok" : t.status === "ERROR" ? "text-status-error" : "text-text-muted"}`}>
                        {t.status}
                      </span>
                    </td>
                    <td className="py-2 text-xs text-text-muted whitespace-nowrap">
                      {new Date(t.started_at).toLocaleString()}
                    </td>
                    <td className="py-2 text-xs text-text-muted tabular-nums">{fmtMs(t.duration_ms)}</td>
                    <td className="py-2 text-xs text-text-muted tabular-nums">{fmtTokens(t.total_tokens)}</td>
                    <td className="py-2 text-xs font-semibold text-text-primary tabular-nums">
                      <div className="flex items-center gap-2">
                        <span>{fmtCost(t.total_cost_usd)}</span>
                        {t.unpriced_model_calls > 0 && (
                          <span className="rounded-full bg-status-warn/15 px-2 py-0.5 text-[10px] text-status-warn">
                            {t.unpriced_model_calls} unpriced
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </ProtectedLayout>
  );
}
