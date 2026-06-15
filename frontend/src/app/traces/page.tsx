"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";

interface Trace {
  id: number;
  external_trace_id: string | null;
  name: string;
  status: string;
  risk_level: string;
  agent_id: number | null;
  environment_id: number | null;
  started_at: string;
  duration_ms: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost: number;
}

interface TracesResponse {
  total: number;
  items: Trace[];
}

const STATUS_COLORS: Record<string, string> = {
  RUNNING: "text-status-info bg-status-info/10",
  SUCCESS: "text-status-ok bg-status-ok/10",
  ERROR: "text-status-error bg-status-error/10",
  BLOCKED: "text-status-warn bg-status-warn/10",
  CANCELLED: "text-text-muted bg-surface-muted",
};

const RISK_COLORS: Record<string, string> = {
  INFO: "text-text-muted",
  LOW: "text-status-ok",
  MEDIUM: "text-status-warn",
  HIGH: "text-status-error",
  CRITICAL: "text-status-error font-bold",
};

function fmtDuration(ms: number | null) {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtCost(cost: number) {
  if (cost === 0) return "—";
  if (cost < 0.01) return `$${cost.toFixed(5)}`;
  return `$${cost.toFixed(4)}`;
}

function fmtTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function TracesPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [riskLevel, setRiskLevel] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (status) params.set("status", status);
  if (riskLevel) params.set("risk_level", riskLevel);
  params.set("limit", String(limit));
  params.set("offset", String(offset));

  const { data, isLoading, isFetching } = useQuery<TracesResponse>({
    queryKey: ["traces", activeOrg?.id, search, status, riskLevel, offset],
    queryFn: () =>
      fetch.get(`/api/v1/organizations/${activeOrg!.id}/traces?${params}`),
    enabled: !!activeOrg,
    placeholderData: (prev) => prev,
  });

  const traces = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <ProtectedLayout>
      <div className="p-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Traces</h1>
          <p className="mt-1 text-sm text-text-secondary">
            {total.toLocaleString()} total{isFetching ? " · refreshing…" : ""}
          </p>
        </div>

        {/* Filters */}
        <div className="mb-4 flex flex-wrap gap-3">
          <input
            value={search}
            onChange={(e) => { setSearch(e.target.value); setOffset(0); }}
            placeholder="Search by trace ID or name…"
            className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:border-brand-500 focus:outline-none w-64"
          />
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
          >
            <option value="">All statuses</option>
            {["RUNNING", "SUCCESS", "ERROR", "BLOCKED", "CANCELLED"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select
            value={riskLevel}
            onChange={(e) => { setRiskLevel(e.target.value); setOffset(0); }}
            className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
          >
            <option value="">All risk levels</option>
            {["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
          {(search || status || riskLevel) && (
            <button
              onClick={() => { setSearch(""); setStatus(""); setRiskLevel(""); setOffset(0); }}
              className="text-sm text-text-muted hover:text-text-secondary"
            >
              Clear filters
            </button>
          )}
        </div>

        {/* Table */}
        <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border">
                {["Trace ID", "Name", "Status", "Risk", "Started", "Duration", "Tokens", "Cost"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-text-muted">Loading…</td></tr>
              ) : traces.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-text-muted">No traces found.</td></tr>
              ) : (
                traces.map((t) => (
                  <tr key={t.id} className="border-b border-surface-border last:border-0 hover:bg-surface-muted/30 transition-colors">
                    <td className="px-4 py-3">
                      <Link href={`/traces/${t.id}`} className="font-mono text-xs text-brand-500 hover:underline">
                        {t.external_trace_id ?? `#${t.id}`}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-text-primary max-w-xs truncate">{t.name}</td>
                    <td className="px-4 py-3">
                      <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", STATUS_COLORS[t.status] ?? "text-text-muted")}>
                        {t.status}
                      </span>
                    </td>
                    <td className={cn("px-4 py-3 text-xs font-medium", RISK_COLORS[t.risk_level] ?? "text-text-muted")}>
                      {t.risk_level}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted whitespace-nowrap">{fmtTime(t.started_at)}</td>
                    <td className="px-4 py-3 text-xs text-text-secondary tabular-nums">{fmtDuration(t.duration_ms)}</td>
                    <td className="px-4 py-3 text-xs text-text-muted tabular-nums">
                      {(t.total_input_tokens + t.total_output_tokens).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-secondary tabular-nums">{fmtCost(t.total_cost)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > limit && (
          <div className="mt-4 flex items-center justify-between text-sm text-text-secondary">
            <span>{offset + 1}–{Math.min(offset + limit, total)} of {total.toLocaleString()}</span>
            <div className="flex gap-2">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                className="rounded-md border border-surface-border px-3 py-1.5 text-xs hover:bg-surface-muted disabled:opacity-40 transition-colors"
              >
                Previous
              </button>
              <button
                disabled={offset + limit >= total}
                onClick={() => setOffset(offset + limit)}
                className="rounded-md border border-surface-border px-3 py-1.5 text-xs hover:bg-surface-muted disabled:opacity-40 transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </ProtectedLayout>
  );
}
