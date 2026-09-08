"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";

interface Approval {
  id: number;
  agent_id: number | null;
  agent_name: string | null;
  external_request_id: string;
  tool_name: string;
  approval_context: Record<string, unknown> | null;
  target_url: string | null;
  trace_name: string | null;
  external_trace_id: string | null;
  status: "pending" | "approved" | "rejected" | "used";
  review_note: string | null;
  reviewed_at: string | null;
  used_at: string | null;
  created_at: string;
}

const statuses = ["pending", "approved", "rejected", "used"] as const;

export default function ApprovalsPage() {
  const { activeOrg } = useAuth();
  const api = useAuthFetch();
  const qc = useQueryClient();
  const [status, setStatus] = useState<string>("pending");
  const [agentFilter, setAgentFilter] = useState("");
  const [toolFilter, setToolFilter] = useState("");
  const [selected, setSelected] = useState<Approval | null>(null);
  const [note, setNote] = useState("");
  const key = ["tool-approvals", activeOrg?.id, status, agentFilter, toolFilter];
  const { data, isLoading } = useQuery<{ items: Approval[] }>({
    queryKey: key,
    queryFn: () => api.get(
      `/api/v1/organizations/${activeOrg!.id}/tool-approvals?${new URLSearchParams({
        status,
        ...(agentFilter ? { agent_id: agentFilter } : {}),
        ...(toolFilter ? { tool: toolFilter } : {}),
      })}`
    ),
    enabled: !!activeOrg,
  });
  const decide = useMutation({
    mutationFn: (outcome: "approve" | "reject") => api.post(
      `/api/v1/organizations/${activeOrg!.id}/tool-approvals/${selected!.id}/${outcome}`,
      { note: note || null },
    ),
    onSuccess: async () => {
      setSelected(null);
      setNote("");
      await qc.invalidateQueries({ queryKey: ["tool-approvals", activeOrg?.id] });
    },
  });

  return (
    <ProtectedLayout>
      <div className="p-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Tool approvals</h1>
          <p className="mt-1 text-sm text-text-muted">
            Review one-time requests before an agent executes a protected tool.
          </p>
        </div>

        <div className="mb-5 flex flex-wrap items-center gap-2">
          {statuses.map((item) => (
            <button
              key={item}
              onClick={() => { setStatus(item); setSelected(null); }}
              className={`rounded-md px-3 py-1.5 text-xs capitalize ${
                status === item
                  ? "bg-brand-500 text-white"
                  : "border border-surface-border text-text-secondary hover:bg-surface-muted"
              }`}
            >
              {item}
            </button>
          ))}
          <input
            value={toolFilter}
            onChange={(event) => setToolFilter(event.target.value)}
            placeholder="Filter tool"
            className="ml-auto rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-text-primary focus:border-brand-500 focus:outline-none"
          />
          <input
            type="number"
            min="1"
            value={agentFilter}
            onChange={(event) => setAgentFilter(event.target.value)}
            placeholder="Agent ID"
            className="w-28 rounded-md border border-surface-border bg-surface px-3 py-1.5 text-xs text-text-primary focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="overflow-hidden rounded-lg border border-surface-border bg-surface-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-surface-border bg-surface-muted text-xs text-text-muted">
              <tr>
                <th className="px-4 py-3">Tool</th>
                <th className="px-4 py-3">Agent</th>
                <th className="px-4 py-3">Trace</th>
                <th className="px-4 py-3">Target</th>
                <th className="px-4 py-3">Requested</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border">
              {data?.items.map((approval) => (
                <tr
                  key={approval.id}
                  onClick={() => { setSelected(approval); setNote(approval.review_note ?? ""); }}
                  className="cursor-pointer hover:bg-surface-muted/60"
                >
                  <td className="px-4 py-3 font-mono text-text-primary">{approval.tool_name}</td>
                  <td className="px-4 py-3 text-text-secondary">{approval.agent_name ?? `#${approval.agent_id}`}</td>
                  <td className="px-4 py-3 text-text-secondary">{approval.trace_name ?? approval.external_trace_id ?? "—"}</td>
                  <td className="max-w-64 truncate px-4 py-3 font-mono text-xs text-text-muted">{approval.target_url ?? "—"}</td>
                  <td className="px-4 py-3 text-text-muted">{new Date(approval.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 capitalize text-text-secondary">{approval.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {isLoading && <p className="p-6 text-sm text-text-muted">Loading approvals…</p>}
          {!isLoading && !data?.items.length && <p className="p-6 text-sm text-text-muted">No {status} approvals.</p>}
        </div>

        {selected && (
          <section className="mt-5 rounded-lg border border-surface-border bg-surface-card p-5">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <h2 className="font-mono text-sm font-semibold text-text-primary">{selected.tool_name}</h2>
                <p className="mt-1 text-xs text-text-muted">Attempt {selected.external_request_id}</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-xs text-text-muted hover:text-text-primary">Close</button>
            </div>
            <dl className="grid gap-3 text-sm md:grid-cols-2">
              <div><dt className="text-xs text-text-muted">Agent</dt><dd className="text-text-primary">{selected.agent_name ?? `#${selected.agent_id}`}</dd></div>
              <div><dt className="text-xs text-text-muted">Trace</dt><dd className="text-text-primary">{selected.trace_name ?? selected.external_trace_id ?? "—"}</dd></div>
              <div className="md:col-span-2"><dt className="text-xs text-text-muted">Safe target</dt><dd className="break-all font-mono text-xs text-text-primary">{selected.target_url ?? "—"}</dd></div>
              <div className="md:col-span-2"><dt className="text-xs text-text-muted">Approval context</dt><dd><pre className="mt-1 overflow-auto rounded bg-surface p-3 text-xs text-text-secondary">{JSON.stringify(selected.approval_context ?? {}, null, 2)}</pre></dd></div>
            </dl>
            {selected.status === "pending" && (
              <div className="mt-4">
                <label className="text-xs text-text-muted">Review note
                  <textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} className="mt-1 block min-h-20 w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none" />
                </label>
                <div className="mt-3 flex justify-end gap-2">
                  <button onClick={() => decide.mutate("reject")} disabled={decide.isPending} className="rounded-md border border-status-error/50 px-4 py-2 text-sm text-status-error hover:bg-status-error/10 disabled:opacity-50">Reject</button>
                  <button onClick={() => decide.mutate("approve")} disabled={decide.isPending} className="rounded-md bg-brand-500 px-4 py-2 text-sm text-white hover:bg-brand-600 disabled:opacity-50">Approve</button>
                </div>
                {decide.isError && <p className="mt-2 text-xs text-status-error">The request was already decided or could not be updated.</p>}
              </div>
            )}
          </section>
        )}
      </div>
    </ProtectedLayout>
  );
}
