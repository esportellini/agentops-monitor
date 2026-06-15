"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

interface Dataset { id: number; name: string; description: string | null; version: string; tags: string[] | null; created_at: string; }

export default function DatasetsPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const { data, isLoading } = useQuery<{ items: Dataset[] }>({
    queryKey: ["eval-datasets", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-datasets`),
    enabled: !!activeOrg,
  });

  async function handleCreate() {
    if (!activeOrg || !name) return;
    setCreating(true);
    try {
      await fetch.post(`/api/v1/organizations/${activeOrg.id}/evaluation-datasets`, { name, description });
      setName(""); setDescription(""); setShowForm(false);
      qc.invalidateQueries({ queryKey: ["eval-datasets", activeOrg.id] });
    } finally { setCreating(false); }
  }

  const datasets = data?.items ?? [];

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-4xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Datasets</h1>
            <p className="mt-1 text-sm text-text-secondary">Collections of test cases for agent evaluation</p>
          </div>
          <button onClick={() => setShowForm(!showForm)} className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 transition-colors">
            + New dataset
          </button>
        </div>

        {showForm && (
          <div className="mb-6 rounded-lg border border-surface-border bg-surface-card p-5 space-y-3">
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Dataset name"
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none" />
            <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="Description (optional)" rows={2}
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none resize-none" />
            <div className="flex gap-2">
              <button onClick={handleCreate} disabled={creating || !name}
                className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50 transition-colors">
                {creating ? "Creating…" : "Create"}
              </button>
              <button onClick={() => setShowForm(false)} className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted transition-colors">Cancel</button>
            </div>
          </div>
        )}

        <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-surface-border">
              {["Name", "Version", "Tags", "Created"].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider">{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-text-muted">Loading…</td></tr>
              ) : datasets.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-text-muted">No datasets yet.</td></tr>
              ) : datasets.map(ds => (
                <tr key={ds.id} className="border-b border-surface-border last:border-0 hover:bg-surface-muted/30">
                  <td className="px-4 py-3">
                    <Link href={`/evaluations/datasets/${ds.id}`} className="font-medium text-text-primary hover:text-brand-500">{ds.name}</Link>
                    {ds.description && <p className="text-xs text-text-muted truncate max-w-xs">{ds.description}</p>}
                  </td>
                  <td className="px-4 py-3 text-xs text-text-secondary">{ds.version}</td>
                  <td className="px-4 py-3 text-xs text-text-muted">{ds.tags?.join(", ") || "—"}</td>
                  <td className="px-4 py-3 text-xs text-text-muted">{new Date(ds.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </ProtectedLayout>
  );
}
