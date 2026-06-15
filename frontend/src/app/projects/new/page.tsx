"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { ApiError } from "@/lib/api";

function toSlug(s: string) {
  return s.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
}

export default function NewProjectPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!activeOrg) return;
    setSaving(true);
    setError(null);
    try {
      const project = await fetch.post<{ id: number }>(
        `/api/v1/organizations/${activeOrg.id}/projects`,
        { name, slug, description: description || null }
      );
      router.push(`/projects/${project.id}`);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? (e instanceof Error ? e.message : "An error occurred") : "Failed to create project");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-lg">
        <h1 className="mb-6 text-xl font-semibold text-text-primary">New project</h1>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md bg-status-error/10 border border-status-error/20 px-3 py-2 text-sm text-status-error">
              {error}
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">Name</label>
            <input
              required
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setSlug(toSlug(e.target.value));
              }}
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
              placeholder="Customer Assistant"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">Slug</label>
            <input
              required
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary font-mono focus:border-brand-500 focus:outline-none"
              placeholder="customer-assistant"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none resize-none"
              placeholder="Optional description"
            />
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
              {saving ? "Creating…" : "Create project"}
            </button>
          </div>
        </form>
      </div>
    </ProtectedLayout>
  );
}
