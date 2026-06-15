"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { StatusBadge } from "@/components/ui/StatusBadge";

interface Project { id: number; name: string; slug: string; description: string | null }
interface Agent { id: number; name: string; slug: string; version: string; status: string; default_model: string | null }
interface Environment { id: number; name: string; type: string }

const STATUS_MAP: Record<string, "ok" | "degraded" | "error" | "unknown"> = {
  ACTIVE: "ok", PAUSED: "degraded", ARCHIVED: "error",
};

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const router = useRouter();
  const qc = useQueryClient();
  const [deleteOpen, setDeleteOpen] = useState(false);

  const { data: project, isLoading } = useQuery<Project>({
    queryKey: ["project", id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/projects/${id}`),
    enabled: !!activeOrg,
  });

  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ["agents", activeOrg?.id, id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/agents?project_id=${id}`),
    enabled: !!activeOrg && !!id,
  });

  const { data: environments = [] } = useQuery<Environment[]>({
    queryKey: ["environments", id],
    queryFn: () =>
      fetch.get(`/api/v1/organizations/${activeOrg!.id}/projects/${id}/environments`),
    enabled: !!activeOrg,
  });

  const deleteProject = useMutation({
    mutationFn: () => fetch.delete(`/api/v1/organizations/${activeOrg!.id}/projects/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      router.push("/projects");
    },
  });

  if (isLoading) return <ProtectedLayout><div className="p-8 text-text-muted text-sm">Loading…</div></ProtectedLayout>;
  if (!project) return <ProtectedLayout><div className="p-8 text-status-error text-sm">Project not found.</div></ProtectedLayout>;

  return (
    <ProtectedLayout>
      <div className="p-8">
        {/* Header */}
        <div className="mb-8 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs text-text-muted mb-1">
              <Link href="/projects" className="hover:text-text-primary">Projects</Link>
              <span>/</span>
              <span className="text-text-secondary">{project.name}</span>
            </div>
            <h1 className="text-xl font-semibold text-text-primary">{project.name}</h1>
            <p className="mt-0.5 font-mono text-xs text-text-muted">/{project.slug}</p>
            {project.description && (
              <p className="mt-2 text-sm text-text-secondary max-w-prose">{project.description}</p>
            )}
          </div>
          <button
            onClick={() => setDeleteOpen(true)}
            className="text-xs text-status-error hover:underline"
          >
            Delete project
          </button>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Agents */}
          <section className="rounded-lg border border-surface-border bg-surface-card p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-text-primary">Agents</h2>
              <Link
                href={`/agents/new?project_id=${project.id}`}
                className="text-xs text-brand-500 hover:underline"
              >
                + New agent
              </Link>
            </div>
            {agents.length === 0 ? (
              <p className="text-xs text-text-muted">No agents yet.</p>
            ) : (
              <ul className="space-y-2">
                {agents.map((a) => (
                  <li key={a.id}>
                    <Link
                      href={`/agents/${a.id}`}
                      className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-surface-muted transition-colors"
                    >
                      <div>
                        <p className="text-sm font-medium text-text-primary">{a.name}</p>
                        <p className="text-xs text-text-muted">v{a.version} · {a.default_model ?? "no model"}</p>
                      </div>
                      <StatusBadge status={STATUS_MAP[a.status] ?? "unknown"} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Environments */}
          <section className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Environments</h2>
            {environments.length === 0 ? (
              <p className="text-xs text-text-muted">No environments configured.</p>
            ) : (
              <ul className="space-y-2">
                {environments.map((e) => (
                  <li key={e.id} className="flex items-center justify-between text-sm">
                    <span className="text-text-primary font-medium">{e.name}</span>
                    <span className="text-xs text-text-muted bg-surface-muted rounded px-2 py-0.5">
                      {e.type}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* Placeholder stats */}
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: "Traces (7d)", value: "—" },
            { label: "Cost (7d)", value: "—" },
            { label: "Error rate", value: "—" },
            { label: "Avg latency", value: "—" },
          ].map(({ label, value }) => (
            <div key={label} className="rounded-lg border border-surface-border bg-surface-card p-4">
              <p className="text-xs text-text-muted uppercase tracking-wider">{label}</p>
              <p className="mt-1.5 text-xl font-semibold text-text-primary">{value}</p>
            </div>
          ))}
        </div>
      </div>

      <ConfirmDialog
        open={deleteOpen}
        title={`Delete "${project.name}"?`}
        description="This will permanently delete the project, all agents, environments, and traces. This cannot be undone."
        confirmLabel="Delete project"
        danger
        onConfirm={() => deleteProject.mutate()}
        onCancel={() => setDeleteOpen(false)}
      />
    </ProtectedLayout>
  );
}
