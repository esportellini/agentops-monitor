"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ApiKey {
  id: number;
  name: string;
  key_prefix: string;
  project_id: number | null;
  status: string;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

function fmt(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function ApiKeysPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null);

  const { data: keys = [], isLoading } = useQuery<ApiKey[]>({
    queryKey: ["api-keys", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/api-keys`),
    enabled: !!activeOrg,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      fetch.post<ApiKey & { key: string }>(`/api/v1/organizations/${activeOrg!.id}/api-keys`, { name }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["api-keys", activeOrg?.id] });
      setNewKey(data.key);
      setName("");
      setCreateError(null);
    },
    onError: (e: Error) => setCreateError(e.message),
  });

  const revokeMutation = useMutation({
    mutationFn: (keyId: number) =>
      fetch.post(`/api/v1/organizations/${activeOrg!.id}/api-keys/${keyId}/revoke`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys", activeOrg?.id] });
      setRevokeTarget(null);
    },
  });

  function copyKey() {
    if (!newKey) return;
    navigator.clipboard.writeText(newKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <ProtectedLayout>
      <div className="p-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">API Keys</h1>
          <p className="mt-1 text-sm text-text-secondary">
            Keys grant programmatic access for trace ingestion and SDK use.
          </p>
        </div>

        {/* Show new key banner once */}
        {newKey && (
          <div className="mb-6 rounded-lg border border-status-ok/30 bg-status-ok/5 p-4">
            <p className="mb-2 text-sm font-medium text-status-ok">
              Key created — copy it now. You won&apos;t see it again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded bg-surface px-3 py-2 text-xs font-mono text-text-primary break-all">
                {newKey}
              </code>
              <button
                onClick={copyKey}
                className="shrink-0 rounded-md border border-surface-border px-3 py-2 text-xs text-text-secondary hover:bg-surface-muted transition-colors"
              >
                {copied ? "Copied!" : "Copy"}
              </button>
              <button
                onClick={() => setNewKey(null)}
                className="shrink-0 text-xs text-text-muted hover:text-text-secondary"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Create key */}
        <div className="mb-6 rounded-lg border border-surface-border bg-surface-card p-5">
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Create key</h2>
          {createError && <p className="mb-2 text-xs text-status-error">{createError}</p>}
          <div className="flex gap-3">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Production ingest"
              className="flex-1 rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:border-brand-500 focus:outline-none"
            />
            <button
              onClick={() => createMutation.mutate()}
              disabled={!name.trim() || createMutation.isPending}
              className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50 transition-colors"
            >
              {createMutation.isPending ? "Creating…" : "Create"}
            </button>
          </div>
        </div>

        {/* Keys table */}
        <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border">
                {["Name", "Prefix", "Scope", "Status", "Created", "Last used", "Expires", ""].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={8} className="px-4 py-6 text-center text-sm text-text-muted">Loading…</td></tr>
              ) : keys.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-6 text-center text-sm text-text-muted">No keys yet.</td></tr>
              ) : (
                keys.map((k) => (
                  <tr key={k.id} className="border-b border-surface-border last:border-0">
                    <td className="px-4 py-3 font-medium text-text-primary">{k.name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-text-secondary">{k.key_prefix}…</td>
                    <td className="px-4 py-3 text-xs text-text-muted">
                      {k.project_id ? `project:${k.project_id}` : "organization"}
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn(
                        "rounded-full px-2 py-0.5 text-xs font-medium",
                        k.status === "ACTIVE" ? "bg-status-ok/15 text-status-ok"
                          : k.status === "REVOKED" ? "bg-status-error/15 text-status-error"
                          : "bg-surface-muted text-text-muted"
                      )}>
                        {k.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted">{fmt(k.created_at)}</td>
                    <td className="px-4 py-3 text-xs text-text-muted">{fmt(k.last_used_at)}</td>
                    <td className="px-4 py-3 text-xs text-text-muted">{fmt(k.expires_at)}</td>
                    <td className="px-4 py-3 text-right">
                      {k.status === "ACTIVE" && (
                        <button
                          onClick={() => setRevokeTarget(k)}
                          className="text-xs text-status-error hover:underline"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <ConfirmDialog
        open={!!revokeTarget}
        title={`Revoke "${revokeTarget?.name}"?`}
        description="Any application using this key will immediately lose access. This cannot be undone."
        confirmLabel="Revoke key"
        danger
        onConfirm={() => revokeTarget && revokeMutation.mutate(revokeTarget.id)}
        onCancel={() => setRevokeTarget(null)}
      />
    </ProtectedLayout>
  );
}
