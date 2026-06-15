"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

interface Project {
  id: number;
  name: string;
  slug: string;
  description: string | null;
  created_at: string;
}

export default function ProjectsPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();

  const { data: projects = [], isLoading } = useQuery<Project[]>({
    queryKey: ["projects", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/projects`),
    enabled: !!activeOrg,
  });

  return (
    <ProtectedLayout>
      <div className="p-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Projects</h1>
            <p className="mt-1 text-sm text-text-secondary">{activeOrg?.name}</p>
          </div>
          <Link
            href="/projects/new"
            className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 transition-colors"
          >
            New project
          </Link>
        </div>

        {isLoading ? (
          <div className="text-sm text-text-muted">Loading…</div>
        ) : projects.length === 0 ? (
          <div className="rounded-lg border border-surface-border bg-surface-card p-10 text-center">
            <p className="text-sm text-text-muted">No projects yet.</p>
            <Link href="/projects/new" className="mt-3 inline-block text-sm text-brand-500 hover:underline">
              Create your first project
            </Link>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className="block rounded-lg border border-surface-border bg-surface-card p-5 hover:border-brand-500/40 transition-colors"
              >
                <h3 className="font-medium text-text-primary">{p.name}</h3>
                <p className="mt-0.5 text-xs text-text-muted font-mono">/{p.slug}</p>
                {p.description && (
                  <p className="mt-2 text-sm text-text-secondary line-clamp-2">{p.description}</p>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </ProtectedLayout>
  );
}
