"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";

interface Finding {
  id: number;
  finding_type: string;
  severity: string;
  title: string;
  description: string;
  action_taken: string;
  agent_id: number | null;
  trace_id: number | null;
  resolved_at: string | null;
  created_at: string;
}

interface Overview {
  unresolved_total: number;
  by_severity: Record<string, number>;
  by_type: { finding_type: string; count: number }[];
  top_agents: { agent_id: number; count: number }[];
}

const SEV_COLORS: Record<string, string> = {
  CRITICAL: "text-red-400 bg-red-400/10 border-red-400/30",
  HIGH: "text-orange-400 bg-orange-400/10 border-orange-400/30",
  MEDIUM: "text-yellow-400 bg-yellow-400/10 border-yellow-400/30",
  LOW: "text-status-ok bg-status-ok/10 border-status-ok/30",
  INFO: "text-text-muted bg-surface-muted border-surface-border",
};

const ACTION_COLORS: Record<string, string> = {
  block: "text-red-400",
  alert: "text-yellow-400",
  redact: "text-blue-400",
  detect: "text-text-muted",
};

const TYPE_LABELS: Record<string, string> = {
  prompt_injection: "Prompt Injection",
  secret_detected: "Secret Detected",
  pii_email: "Email (PII)",
  pii_phone: "Phone (PII)",
  pii_cpf: "CPF (PII)",
  pii_card: "Card Number",
  api_key_detected: "API Key",
  bearer_token_detected: "Bearer Token",
  credential_detected: "Credential",
  domain_blocked: "Blocked Domain",
  tool_unauthorized: "Unauthorized Tool",
  token_limit_exceeded: "Token Limit",
  cost_limit_exceeded: "Cost Limit",
  sql_dangerous: "Dangerous SQL",
  output_scope_violation: "Scope Violation",
  abnormal_behavior: "Abnormal Behavior",
};

export default function SecurityPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const [filter, setFilter] = useState<"all" | "unresolved">("unresolved");
  const [severityFilter, setSeverityFilter] = useState("");

  const params = new URLSearchParams({ limit: "100" });
  if (filter === "unresolved") params.set("resolved", "false");
  if (severityFilter) params.set("severity", severityFilter);

  const { data: overview } = useQuery<Overview>({
    queryKey: ["security-overview", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/security/overview`),
    enabled: !!activeOrg,
  });

  const { data: findingsData, isLoading } = useQuery<{ total: number; items: Finding[] }>({
    queryKey: ["security-findings", activeOrg?.id, filter, severityFilter],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/security/findings?${params}`),
    enabled: !!activeOrg,
  });

  const findings = findingsData?.items ?? [];

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-6xl">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Security</h1>
          <p className="mt-1 text-sm text-text-secondary">
            Findings, policies, and threat detection
          </p>
        </div>

        {/* Overview cards */}
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          <div className="rounded-lg border border-red-400/30 bg-red-400/5 p-4">
            <p className="text-xs text-text-muted">Unresolved</p>
            <p className="mt-1 text-2xl font-bold text-red-400">{overview?.unresolved_total ?? 0}</p>
          </div>
          {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((sev) => (
            <div key={sev} className={cn("rounded-lg border p-4", SEV_COLORS[sev])}>
              <p className="text-xs opacity-70">{sev}</p>
              <p className="mt-1 text-2xl font-bold">{overview?.by_severity?.[sev] ?? 0}</p>
            </div>
          ))}
        </div>

        {/* Most common finding types */}
        {overview?.by_type && overview.by_type.length > 0 && (
          <div className="mb-6 rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-3 text-sm font-semibold text-text-primary">Most common findings</h2>
            <div className="space-y-2">
              {overview.by_type.slice(0, 8).map((t) => {
                const max = overview.by_type[0].count;
                return (
                  <div key={t.finding_type} className="flex items-center gap-3">
                    <span className="w-40 shrink-0 text-xs text-text-secondary truncate">
                      {TYPE_LABELS[t.finding_type] ?? t.finding_type}
                    </span>
                    <div className="flex-1 h-2 rounded-full bg-surface-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-brand-500"
                        style={{ width: `${(t.count / max) * 100}%` }}
                      />
                    </div>
                    <span className="w-8 text-right text-xs tabular-nums text-text-muted">{t.count}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="mb-4 flex flex-wrap gap-3">
          <div className="flex rounded-md border border-surface-border overflow-hidden">
            {(["unresolved", "all"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium transition-colors",
                  filter === f
                    ? "bg-brand-500 text-white"
                    : "text-text-secondary hover:bg-surface-muted",
                )}
              >
                {f === "unresolved" ? "Unresolved" : "All"}
              </button>
            ))}
          </div>
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-text-primary focus:border-brand-500 focus:outline-none"
          >
            <option value="">All severities</option>
            {["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          {severityFilter && (
            <button onClick={() => setSeverityFilter("")} className="text-xs text-text-muted hover:text-text-secondary">
              Clear
            </button>
          )}
        </div>

        {/* Findings table */}
        <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border">
                {["Severity", "Type", "Title", "Action", "Agent", "Trace", "Time"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-text-muted">Loading…</td></tr>
              ) : findings.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-text-muted">No findings.</td></tr>
              ) : (
                findings.map((f) => (
                  <tr key={f.id} className="border-b border-surface-border last:border-0 hover:bg-surface-muted/30 transition-colors">
                    <td className="px-4 py-3">
                      <span className={cn("rounded border px-1.5 py-0.5 text-xs font-medium", SEV_COLORS[f.severity] ?? "")}>
                        {f.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-text-secondary">
                      {TYPE_LABELS[f.finding_type] ?? f.finding_type}
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/security/findings/${f.id}`} className="text-sm text-text-primary hover:text-brand-500">
                        {f.title}
                      </Link>
                      <p className="text-xs text-text-muted truncate max-w-xs">{f.description}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn("text-xs font-medium", ACTION_COLORS[f.action_taken] ?? "text-text-muted")}>
                        {f.action_taken}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted">
                      {f.agent_id ? `#${f.agent_id}` : "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted">
                      {f.trace_id ? (
                        <Link href={`/traces/${f.trace_id}`} className="text-brand-500 hover:underline">
                          #{f.trace_id}
                        </Link>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted whitespace-nowrap">
                      {new Date(f.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </ProtectedLayout>
  );
}
