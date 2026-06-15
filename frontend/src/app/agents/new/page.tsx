"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { ApiError } from "@/lib/api";

interface Project { id: number; name: string }

function toSlug(s: string) {
  return s.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
}

// Isolated to a child so useSearchParams is inside the Suspense boundary
function NewAgentForm() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const router = useRouter();
  const params = useSearchParams();

  const [projectId, setProjectId] = useState(params.get("project_id") ?? "");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [version, setVersion] = useState("0.1.0");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [budget, setBudget] = useState("");
  const [tokenLimit, setTokenLimit] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ["projects", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/projects`),
    enabled: !!activeOrg,
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!activeOrg || !projectId) return;
    setSaving(true);
    setError(null);
    try {
      const agent = await fetch.post<{ id: number }>(
        `/api/v1/organizations/${activeOrg.id}/agents`,
        {
          project_id: Number(projectId),
          name,
          slug,
          description: description || null,
          version,
          model_provider: provider || null,
          default_model: model || null,
          monthly_budget_usd: budget ? Number(budget) : null,
          token_limit_per_trace: tokenLimit ? Number(tokenLimit) : null,
        }
      );
      router.push(`/agents/${agent.id}`);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? (e instanceof Error ? e.message : "An error occurred") : "Failed to create agent");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="rounded-md bg-status-error/10 border border-status-error/20 px-3 py-2 text-sm text-status-error">
          {error}
        </div>
      )}

      <div>
        <label className="block text-xs font-medium text-text-secondary mb-1.5">Project</label>
        <select
          required
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
        >
          <option value="">Select a project…</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-text-secondary mb-1.5">Name</label>
        <input
          required
          value={name}
          onChange={(e) => { setName(e.target.value); setSlug(toSlug(e.target.value)); }}
          className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
          placeholder="Support Bot"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-text-secondary mb-1.5">Slug</label>
        <input
          required
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary font-mono focus:border-brand-500 focus:outline-none"
          placeholder="support-bot"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-text-secondary mb-1.5">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none resize-none"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">Provider</label>
          <input
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            placeholder="openai"
            className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">Model</label>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="gpt-4o"
            className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">Monthly budget (USD)</label>
          <input
            type="number"
            min="0"
            step="0.01"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="50.00"
            className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">Token limit / trace</label>
          <input
            type="number"
            min="0"
            value={tokenLimit}
            onChange={(e) => setTokenLimit(e.target.value)}
            placeholder="10000"
            className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
          />
        </div>
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={() => router.back()}
          className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50 transition-colors"
        >
          {saving ? "Creating…" : "Create agent"}
        </button>
      </div>
    </form>
  );
}

export default function NewAgentPage() {
  return (
    <ProtectedLayout>
      <div className="p-8 max-w-lg">
        <h1 className="mb-6 text-xl font-semibold text-text-primary">New agent</h1>
        <Suspense fallback={<div className="text-sm text-text-muted">Loading…</div>}>
          <NewAgentForm />
        </Suspense>
      </div>
    </ProtectedLayout>
  );
}
