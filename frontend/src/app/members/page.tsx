"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

interface Member {
  id: number;
  user_id: number;
  role: string;
  user: { id: number; email: string; name: string };
}

const ROLES = ["OWNER", "ADMIN", "DEVELOPER", "ANALYST", "VIEWER"];

export default function MembersPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("VIEWER");
  const [inviting, setInviting] = useState(false);
  const [error, setError] = useState("");

  const { data, isLoading } = useQuery<{ items: Member[] }>({
    queryKey: ["members", activeOrg?.id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/members`),
    enabled: !!activeOrg,
  });

  const members = data?.items ?? [];

  async function handleInvite() {
    if (!activeOrg || !email) return;
    setInviting(true);
    setError("");
    try {
      await fetch.post(`/api/v1/organizations/${activeOrg.id}/members`, { email, role });
      setEmail("");
      qc.invalidateQueries({ queryKey: ["members", activeOrg.id] });
    } catch (e: any) {
      setError(e.message ?? "Failed to invite member");
    } finally {
      setInviting(false);
    }
  }

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-3xl">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Members</h1>
          <p className="mt-1 text-sm text-text-secondary">Manage organization members and roles</p>
        </div>

        <div className="mb-6 rounded-lg border border-surface-border bg-surface-card p-5">
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Invite member</h2>
          <div className="flex gap-3">
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              className="flex-1 rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none"
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:outline-none"
            >
              {ROLES.map((r) => <option key={r}>{r}</option>)}
            </select>
            <button
              onClick={handleInvite}
              disabled={inviting || !email}
              className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50 transition-colors"
            >
              {inviting ? "Inviting…" : "Invite"}
            </button>
          </div>
          {error && <p className="mt-2 text-xs text-status-error">{error}</p>}
        </div>

        <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border">
                {["Name", "Email", "Role"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={3} className="px-4 py-8 text-center text-sm text-text-muted">Loading…</td></tr>
              ) : members.length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-8 text-center text-sm text-text-muted">No members yet.</td></tr>
              ) : members.map((m) => (
                <tr key={m.id} className="border-b border-surface-border last:border-0">
                  <td className="px-4 py-3 font-medium text-text-primary">{m.user.name}</td>
                  <td className="px-4 py-3 text-text-secondary">{m.user.email}</td>
                  <td className="px-4 py-3">
                    <span className="rounded border border-surface-border px-2 py-0.5 text-xs text-text-secondary">{m.role}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </ProtectedLayout>
  );
}
