"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { StatusBadge } from "@/components/ui/StatusBadge";

interface Agent {
  id: number;
  name: string;
  slug: string;
  version: string;
  status: string;
  model_provider: string | null;
  default_model: string | null;
  project_id: number;
}

const STATUS_MAP: Record<string, "ok" | "degraded" | "error" | "unknown"> = {
  ACTIVE: "ok", PAUSED: "degraded", ARCHIVED: "error",
};

export default function AgentsPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();

  const { data: agents = [], isLoading } = useQuery<Agent[]>({
    queryKey: ["agents", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/agents`),
    enabled: !!activeOrg,
  });

  return (
    <ProtectedLayout>
      <div className="p-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-text-primary">Agents</h1>
          <Link
            href="/agents/new"
            className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 transition-colors"
          >
            New agent
          </Link>
        </div>

        {isLoading ? (
          <p className="text-sm text-text-muted">Loading…</p>
        ) : agents.length === 0 ? (
          <div className="rounded-lg border border-surface-border bg-surface-card p-10 text-center">
            <p className="text-sm text-text-muted">No agents yet.</p>
            <Link href="/agents/new" className="mt-3 inline-block text-sm text-brand-500 hover:underline">
              Create your first agent
            </Link>
          </div>
        ) : (
          <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border">
                  <th className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider">Agent</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider">Version</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider">Model</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((a) => (
                  <tr key={a.id} className="border-b border-surface-border last:border-0 hover:bg-surface-muted/30 transition-colors">
                    <td className="px-4 py-3">
                      <Link href={`/agents/${a.id}`} className="font-medium text-text-primary hover:text-brand-500">
                        {a.name}
                      </Link>
                      <p className="text-xs text-text-muted font-mono">/{a.slug}</p>
                    </td>
                    <td className="px-4 py-3 text-text-secondary font-mono text-xs">v{a.version}</td>
                    <td className="px-4 py-3 text-text-secondary text-xs">
                      {a.default_model ? `${a.model_provider}/${a.default_model}` : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={STATUS_MAP[a.status] ?? "unknown"} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </ProtectedLayout>
  );
}
