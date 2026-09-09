"use client";

import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";

interface Finding {
  id: number;
  finding_type: string;
  severity: string;
  title: string;
  description: string;
  evidence: Record<string, unknown> | null;
  action_taken: string;
  redacted_content: string | null;
  agent_id: number | null;
  trace_id: number | null;
  span_id: number | null;
  resolved_at: string | null;
  resolved_by_id: number | null;
  resolution_note: string | null;
  created_at: string;
}

const SEV_BADGE: Record<string, string> = {
  CRITICAL: "text-status-error bg-status-error/10 border border-status-error/30",
  HIGH: "text-status-error bg-status-error/10 border border-status-error/30",
  MEDIUM: "text-status-warn bg-status-warn/10 border border-status-warn/30",
  LOW: "text-status-ok bg-status-ok/10 border border-status-ok/30",
  INFO: "text-text-muted bg-surface-muted border border-surface-border",
};

export default function FindingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);

  const { data: finding, isLoading } = useQuery<Finding>({
    queryKey: ["finding", id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/security/findings/${id}`),
    enabled: !!activeOrg,
  });

  async function handleResolve() {
    if (!activeOrg || !finding) return;
    setResolving(true);
    try {
      await fetch.post(
        `/api/v1/organizations/${activeOrg.id}/security/findings/${id}/resolve`,
        { note }
      );
      qc.invalidateQueries({ queryKey: ["finding", id] });
      qc.invalidateQueries({ queryKey: ["security-findings"] });
    } finally {
      setResolving(false);
    }
  }

  if (isLoading) return <ProtectedLayout><div className="p-8 text-sm text-text-muted">Loading…</div></ProtectedLayout>;
  if (!finding) return <ProtectedLayout><div className="p-8 text-sm text-status-error">Finding not found.</div></ProtectedLayout>;

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-3xl">
        {/* Breadcrumb */}
        <div className="mb-4 text-xs text-text-muted">
          <Link href="/security" className="hover:text-text-primary">Security</Link>
          {" / "}
          <span>Finding #{finding.id}</span>
        </div>

        {/* Header */}
        <div className="mb-6 rounded-lg border border-surface-border bg-surface-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className={cn("rounded px-2 py-0.5 text-xs font-medium", SEV_BADGE[finding.severity])}>
                  {finding.severity}
                </span>
                <span className="text-xs text-text-muted">{finding.finding_type}</span>
                {finding.resolved_at && (
                  <span className="rounded px-2 py-0.5 text-xs font-medium text-status-ok bg-status-ok/10">
                    RESOLVED
                  </span>
                )}
              </div>
              <h1 className="text-lg font-semibold text-text-primary">{finding.title}</h1>
              <p className="mt-1 text-sm text-text-secondary">{finding.description}</p>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-4 text-sm">
            {[
              ["Action taken", finding.action_taken],
              ["Detected", new Date(finding.created_at).toLocaleString()],
              ["Agent", finding.agent_id ? `#${finding.agent_id}` : "—"],
            ].map(([label, value]) => (
              <div key={label as string}>
                <p className="text-xs text-text-muted">{label}</p>
                <p className="mt-0.5 text-text-primary font-medium">{value}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4">
          {/* Links */}
          {(finding.trace_id || finding.span_id) && (
            <section className="rounded-lg border border-surface-border bg-surface-card p-4">
              <h2 className="mb-3 text-sm font-semibold text-text-primary">Context</h2>
              <div className="flex gap-4 text-sm">
                {finding.trace_id && (
                  <Link href={`/traces/${finding.trace_id}`} className="text-brand-500 hover:underline">
                    View trace #{finding.trace_id}
                  </Link>
                )}
              </div>
            </section>
          )}

          {/* Evidence */}
          {finding.evidence && (
            <section className="rounded-lg border border-surface-border bg-surface-card p-4">
              <h2 className="mb-3 text-sm font-semibold text-text-primary">Evidence</h2>
              <pre className="text-xs text-text-secondary overflow-x-auto">
                {JSON.stringify(finding.evidence, null, 2)}
              </pre>
            </section>
          )}

          {/* Redacted content */}
          {finding.redacted_content && (
            <section className="rounded-lg border border-status-info/20 bg-status-info/5 p-4">
              <h2 className="mb-2 text-sm font-semibold text-status-info">Redacted content</h2>
              <pre className="text-xs text-text-secondary overflow-x-auto whitespace-pre-wrap">
                {finding.redacted_content}
              </pre>
            </section>
          )}

          {/* Resolution */}
          {finding.resolved_at ? (
            <section className="rounded-lg border border-status-ok/20 bg-status-ok/5 p-4">
              <h2 className="mb-2 text-sm font-semibold text-status-ok">Resolved</h2>
              <p className="text-xs text-text-secondary">
                {new Date(finding.resolved_at).toLocaleString()}
                {finding.resolved_by_id && ` · by user #${finding.resolved_by_id}`}
              </p>
              {finding.resolution_note && (
                <p className="mt-2 text-sm text-text-primary">{finding.resolution_note}</p>
              )}
            </section>
          ) : (
            <section className="rounded-lg border border-surface-border bg-surface-card p-4">
              <h2 className="mb-3 text-sm font-semibold text-text-primary">Resolve finding</h2>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Add a resolution note (optional)…"
                rows={3}
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none resize-none mb-3"
              />
              <button
                onClick={handleResolve}
                disabled={resolving}
                className="rounded-md bg-status-ok px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {resolving ? "Resolving…" : "Mark as resolved"}
              </button>
            </section>
          )}
        </div>
      </div>
    </ProtectedLayout>
  );
}
