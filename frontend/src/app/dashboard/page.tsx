"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";

interface Overview {
  executions_total: number;
  executions_today: number;
  success_rate: number;
  errors: number;
  blocked: number;
  avg_latency_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  cost_today_usd: number;
  cost_mtd_usd: number;
  cost_projection_usd: number;
  active_agents: number;
}

interface TimeseriesRow {
  bucket: string;
  executions: number;
  success: number;
  errors: number;
  success_rate: number;
  avg_latency_ms: number;
  cost_usd: number;
}

interface AgentRow {
  agent_id: number;
  agent_name: string;
  executions: number;
  success_rate: number;
  total_cost_usd: number;
  avg_cost_per_execution_usd: number;
}

interface ModelRow {
  provider: string;
  model: string;
  calls: number;
  total_cost_usd: number;
  total_tokens: number;
}

function fmtCost(n: number) {
  if (n === 0) return "$0.00";
  if (n < 0.001) return `$${n.toFixed(6)}`;
  if (n < 1) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmtNumber(n: number) {
  return n.toLocaleString();
}

function fmtMs(ms: number) {
  if (!ms) return "—";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// Simple bar chart using CSS
function MiniBarChart({ data, valueKey, labelKey, color = "brand" }: {
  data: Record<string, any>[];
  valueKey: string;
  labelKey: string;
  color?: string;
}) {
  if (!data.length) return <p className="text-xs text-text-muted">No data</p>;
  const max = Math.max(...data.map((d) => d[valueKey] || 0));
  return (
    <div className="space-y-1.5">
      {data.slice(0, 8).map((d, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className="w-28 truncate text-text-secondary shrink-0">{d[labelKey]}</span>
          <div className="flex-1 bg-surface-muted rounded-full h-2 overflow-hidden">
            <div
              className={cn("h-2 rounded-full", color === "brand" ? "bg-brand-500" : "bg-status-ok")}
              style={{ width: max > 0 ? `${(d[valueKey] / max) * 100}%` : "0%" }}
            />
          </div>
          <span className="text-text-muted w-16 text-right shrink-0">
            {valueKey.includes("cost") ? fmtCost(d[valueKey]) : fmtNumber(d[valueKey])}
          </span>
        </div>
      ))}
    </div>
  );
}

// Sparkline from timeseries using SVG
function Sparkline({ data, valueKey, color = "#6366f1" }: {
  data: Record<string, any>[];
  valueKey: string;
  color?: string;
}) {
  if (data.length < 2) return null;
  const values = data.map((d) => d[valueKey] || 0);
  const max = Math.max(...values, 1);
  const min = Math.min(...values);
  const range = max - min || 1;
  const w = 200;
  const h = 40;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  });
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-10">
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

function KpiCard({ label, value, sub, trend }: {
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | "neutral";
}) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-card p-4">
      <p className="text-xs text-text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-text-primary tabular-nums">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-text-muted">{sub}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const base = `/api/v1/organizations/${activeOrg?.id}`;

  const { data: overview } = useQuery<Overview>({
    queryKey: ["overview", activeOrg?.id],
    queryFn: () => fetch.get(`${base}/metrics/overview`),
    enabled: !!activeOrg,
    refetchInterval: 30_000,
  });

  const { data: timeseries = [] } = useQuery<TimeseriesRow[]>({
    queryKey: ["timeseries", activeOrg?.id],
    queryFn: () => fetch.get(`${base}/metrics/timeseries?days=30`),
    enabled: !!activeOrg,
  });

  const { data: agents = [] } = useQuery<AgentRow[]>({
    queryKey: ["agent-metrics", activeOrg?.id],
    queryFn: () => fetch.get(`${base}/metrics/agents?days=30`),
    enabled: !!activeOrg,
  });

  const { data: models = [] } = useQuery<ModelRow[]>({
    queryKey: ["model-metrics", activeOrg?.id],
    queryFn: () => fetch.get(`${base}/metrics/models?days=30`),
    enabled: !!activeOrg,
  });

  const ov = overview;

  return (
    <ProtectedLayout>
      <div className="p-8 space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Dashboard</h1>
          <p className="mt-1 text-sm text-text-secondary">Last 30 days</p>
        </div>

        {/* KPI cards */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          <KpiCard label="Executions today" value={fmtNumber(ov?.executions_today ?? 0)} />
          <KpiCard label="Success rate" value={`${ov?.success_rate ?? 0}%`} sub="last 30 days" />
          <KpiCard label="Errors" value={fmtNumber(ov?.errors ?? 0)} />
          <KpiCard label="Blocked" value={fmtNumber(ov?.blocked ?? 0)} />
          <KpiCard
            label="Avg latency"
            value={fmtMs(ov?.avg_latency_ms ?? 0)}
          />
          <KpiCard label="Active agents" value={fmtNumber(ov?.active_agents ?? 0)} />
          <KpiCard label="Cost today" value={fmtCost(ov?.cost_today_usd ?? 0)} />
          <KpiCard
            label="Cost this month"
            value={fmtCost(ov?.cost_mtd_usd ?? 0)}
            sub={`Proj: ${fmtCost(ov?.cost_projection_usd ?? 0)}`}
          />
          <KpiCard
            label="Input tokens"
            value={fmtTokens(ov?.total_input_tokens ?? 0)}
          />
          <KpiCard
            label="Output tokens"
            value={fmtTokens(ov?.total_output_tokens ?? 0)}
          />
          <KpiCard label="Total executions" value={fmtNumber(ov?.executions_total ?? 0)} sub="last 30 days" />
          <KpiCard label="Monthly projection" value={fmtCost(ov?.cost_projection_usd ?? 0)} />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Executions timeseries */}
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Executions per day</h2>
            <Sparkline data={timeseries} valueKey="executions" color="#6366f1" />
            <div className="mt-3 flex justify-between text-xs text-text-muted">
              {timeseries.slice(0, 1).map((d) => (
                <span key={d.bucket}>{new Date(d.bucket).toLocaleDateString()}</span>
              ))}
              {timeseries.slice(-1).map((d) => (
                <span key={d.bucket}>{new Date(d.bucket).toLocaleDateString()}</span>
              ))}
            </div>
          </div>

          {/* Cost timeseries */}
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Cost per day (USD)</h2>
            <Sparkline data={timeseries} valueKey="cost_usd" color="#10b981" />
            <div className="mt-3 flex justify-between text-xs text-text-muted">
              {timeseries.slice(0, 1).map((d) => (
                <span key={d.bucket}>{fmtCost(d.cost_usd)}</span>
              ))}
              {timeseries.slice(-1).map((d) => (
                <span key={d.bucket}>{fmtCost(d.cost_usd)}</span>
              ))}
            </div>
          </div>

          {/* Success rate timeseries */}
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Success rate (%)</h2>
            <Sparkline data={timeseries} valueKey="success_rate" color="#10b981" />
          </div>

          {/* Latency timeseries */}
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Avg latency (ms)</h2>
            <Sparkline data={timeseries} valueKey="avg_latency_ms" color="#f59e0b" />
          </div>
        </div>

        {/* Tables row */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Most expensive agents */}
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Most expensive agents</h2>
            <MiniBarChart
              data={agents}
              valueKey="total_cost_usd"
              labelKey="agent_name"
              color="brand"
            />
          </div>

          {/* Model distribution */}
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Cost by model</h2>
            <MiniBarChart
              data={models.map((m) => ({ ...m, label: `${m.provider}/${m.model}` }))}
              valueKey="total_cost_usd"
              labelKey="label"
              color="brand"
            />
          </div>

          {/* Executions per agent */}
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Executions per agent</h2>
            <MiniBarChart
              data={agents}
              valueKey="executions"
              labelKey="agent_name"
              color="neutral"
            />
          </div>

          {/* Model calls volume */}
          <div className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Model calls volume</h2>
            <MiniBarChart
              data={models.map((m) => ({ ...m, label: `${m.provider}/${m.model}` }))}
              valueKey="calls"
              labelKey="label"
              color="neutral"
            />
          </div>
        </div>
      </div>
    </ProtectedLayout>
  );
}
