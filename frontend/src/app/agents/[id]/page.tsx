"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { AgentPolicyEditor } from "@/components/agents/AgentPolicyEditor";

interface Agent {
  id: number;
  name: string;
  slug: string;
  version: string;
  status: string;
  model_provider: string | null;
  default_model: string | null;
  description: string | null;
  monthly_budget_usd: number | null;
  token_limit_per_trace: number | null;
  project_id: number;
  owner_user_id: number | null;
}

const STATUS_BADGE: Record<string, "ok" | "degraded" | "error" | "unknown"> = {
  ACTIVE: "ok", PAUSED: "degraded", ARCHIVED: "error",
};

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [newVersion, setNewVersion] = useState("");

  const { data: agent, isLoading } = useQuery<Agent>({
    queryKey: ["agent", id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/agents/${id}`),
    enabled: !!activeOrg,
  });

  const statusMutation = useMutation({
    mutationFn: (status: string) =>
      fetch.patch(`/api/v1/organizations/${activeOrg!.id}/agents/${id}/status`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent", id] }),
  });

  const versionMutation = useMutation({
    mutationFn: (version: string) =>
      fetch.post(`/api/v1/organizations/${activeOrg!.id}/agents/${id}/new-version`, { version }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent", id] });
      setNewVersion("");
    },
  });

  if (isLoading) return <ProtectedLayout><div className="p-8 text-sm text-text-muted">Loading…</div></ProtectedLayout>;
  if (!agent) return <ProtectedLayout><div className="p-8 text-sm text-status-error">Agent not found.</div></ProtectedLayout>;

  return (
    <ProtectedLayout>
      <div className="p-8">
        {/* Header */}
        <div className="mb-8 flex items-start justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">{agent.name}</h1>
            <p className="mt-0.5 font-mono text-xs text-text-muted">/{agent.slug} · v{agent.version}</p>
            {agent.description && (
              <p className="mt-2 text-sm text-text-secondary max-w-prose">{agent.description}</p>
            )}
          </div>
          <StatusBadge status={STATUS_BADGE[agent.status] ?? "unknown"} />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Configuration */}
          <section className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Configuration</h2>
            <dl className="space-y-3 text-sm">
              {[
                ["Provider", agent.model_provider ?? "—"],
                ["Model", agent.default_model ?? "—"],
                ["Monthly budget", agent.monthly_budget_usd != null ? `$${agent.monthly_budget_usd.toFixed(2)}` : "Unlimited"],
                ["Token limit / trace", agent.token_limit_per_trace?.toLocaleString() ?? "Unlimited"],
                ["Status", agent.status],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-text-muted">{label}</dt>
                  <dd className="text-text-primary font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          </section>

          {/* Actions */}
          <section className="rounded-lg border border-surface-border bg-surface-card p-5 space-y-5">
            <div>
              <h2 className="mb-3 text-sm font-semibold text-text-primary">Bump version</h2>
              <div className="flex gap-2">
                <input
                  value={newVersion}
                  onChange={(e) => setNewVersion(e.target.value)}
                  placeholder={`${agent.version} → auto`}
                  className="flex-1 rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary font-mono focus:border-brand-500 focus:outline-none"
                />
                <button
                  onClick={() => versionMutation.mutate(newVersion)}
                  disabled={versionMutation.isPending}
                  className="rounded-md bg-brand-500 px-3 py-2 text-sm text-white hover:bg-brand-600 disabled:opacity-50 transition-colors"
                >
                  Bump
                </button>
              </div>
            </div>

            <div>
              <h2 className="mb-3 text-sm font-semibold text-text-primary">Status</h2>
              <div className="flex gap-2">
                {agent.status !== "ACTIVE" && (
                  <button
                    onClick={() => statusMutation.mutate("ACTIVE")}
                    className="rounded-md border border-status-ok/40 px-3 py-1.5 text-xs text-status-ok hover:bg-status-ok/10 transition-colors"
                  >
                    Activate
                  </button>
                )}
                {agent.status !== "PAUSED" && (
                  <button
                    onClick={() => statusMutation.mutate("PAUSED")}
                    className="rounded-md border border-status-warn/40 px-3 py-1.5 text-xs text-status-warn hover:bg-status-warn/10 transition-colors"
                  >
                    Pause
                  </button>
                )}
                {agent.status !== "ARCHIVED" && (
                  <button
                    onClick={() => setArchiveOpen(true)}
                    className="rounded-md border border-status-error/40 px-3 py-1.5 text-xs text-status-error hover:bg-status-error/10 transition-colors"
                  >
                    Archive
                  </button>
                )}
              </div>
            </div>
          </section>
        </div>

        <AgentPolicyEditor orgId={activeOrg!.id} agentId={agent.id} />

        {/* Placeholder metrics */}
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: "Success rate", value: "—" },
            { label: "Avg cost / trace", value: "—" },
            { label: "Avg latency", value: "—" },
            { label: "Errors (24h)", value: "—" },
          ].map(({ label, value }) => (
            <div key={label} className="rounded-lg border border-surface-border bg-surface-card p-4">
              <p className="text-xs text-text-muted uppercase tracking-wider">{label}</p>
              <p className="mt-1.5 text-xl font-semibold text-text-primary">{value}</p>
            </div>
          ))}
        </div>
      </div>

      <ConfirmDialog
        open={archiveOpen}
        title={`Archive "${agent.name}"?`}
        description="Archived agents stop accepting new traces. You can reactivate later."
        confirmLabel="Archive"
        danger
        onConfirm={() => { statusMutation.mutate("ARCHIVED"); setArchiveOpen(false); }}
        onCancel={() => setArchiveOpen(false)}
      />
    </ProtectedLayout>
  );
}
