"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";

interface DataMapItem { category: string; table: string; sensitivity: string; purpose: string; contains_pii_risk: boolean; can_disable: boolean; note?: string; }
interface RetentionPolicy { id: number|null; traces_retention_days: number|null; spans_retention_days: number|null; audit_logs_retention_days: number|null; cost_records_retention_days: number|null; anonymize_user_references: boolean; }
interface PrivacyRequest { id: number; type: string; status: string; subject_reference: string; notes: string|null; created_at: string; completed_at: string|null; }

const SENS: Record<string,string> = { CRITICAL: "text-status-error", HIGH: "text-status-error", MEDIUM: "text-status-warn", LOW: "text-status-ok" };
const STATUS_C: Record<string,string> = { PENDING: "text-status-warn", IN_PROGRESS: "text-brand-500", COMPLETED: "text-status-ok", REJECTED: "text-status-error" };

export default function PrivacyPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"map"|"retention"|"requests"|"actions">("map");
  const [subject, setSubject] = useState("");
  const [reqType, setReqType] = useState("EXPORT");
  const [reqNote, setReqNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string|null>(null);

  const { data: mapData } = useQuery<{ items: DataMapItem[] }>({
    queryKey: ["privacy-map"], queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/privacy/data-map`), enabled: !!activeOrg,
  });
  const { data: policy } = useQuery<RetentionPolicy>({
    queryKey: ["privacy-policy", activeOrg?.id], queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/privacy/retention-policies`), enabled: !!activeOrg,
  });
  const { data: requests } = useQuery<{ items: PrivacyRequest[] }>({
    queryKey: ["privacy-requests", activeOrg?.id], queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/privacy/requests`), enabled: !!activeOrg,
  });

  async function handleAction(action: "export"|"anonymize"|"retention"|"request") {
    if (!activeOrg) return;
    setSubmitting(true); setResult(null);
    try {
      if (action === "export") {
        const r = await fetch.post(`/api/v1/organizations/${activeOrg.id}/privacy/export`, { subject_reference: subject || undefined, format: "json" }) as any;
        const parsed = typeof r?.data === "string" ? JSON.parse(r.data) : (r?.data ?? r);
        setResult(`Export complete. ${parsed?.traces?.length ?? 0} traces exported.`);
      } else if (action === "anonymize") {
        const r = await fetch.post(`/api/v1/organizations/${activeOrg.id}/privacy/anonymize`, { subject_reference: subject }) as any;
        setResult(`Anonymized. ${r?.traces_anonymized ?? 0} traces updated → ${r?.anonymized_as ?? "?"}`);
      } else if (action === "retention") {
        const r = await fetch.post(`/api/v1/organizations/${activeOrg.id}/privacy/run-retention`, {}) as any;
        setResult(`Retention executed. Traces deleted: ${r?.traces ?? 0}, Audit logs: ${r?.audit_logs ?? 0}`);
      } else if (action === "request") {
        await fetch.post(`/api/v1/organizations/${activeOrg.id}/privacy/requests`, { type: reqType, subject_reference: subject, notes: reqNote });
        qc.invalidateQueries({ queryKey: ["privacy-requests", activeOrg.id] });
        setResult("Privacy request created.");
      }
    } catch (e: unknown) {
      setResult(`Error: ${e instanceof Error ? e.message : "Unknown error"}`);
    } finally { setSubmitting(false); }
  }

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-5xl">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Privacy & LGPD</h1>
          <p className="mt-1 text-sm text-text-secondary">Data governance, retention policies, and subject rights</p>
        </div>

        <div className="mb-6 flex gap-1 border-b border-surface-border">
          {(["map","retention","requests","actions"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} className={cn("px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px", tab===t ? "border-brand-500 text-brand-500" : "border-transparent text-text-muted hover:text-text-secondary")}>
              {t === "map" ? "Data map" : t === "retention" ? "Retention" : t === "requests" ? "Requests" : "Actions"}
            </button>
          ))}
        </div>

        {tab === "map" && (
          <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-surface-border">
                {["Category","Table","Sensitivity","Purpose","PII Risk","Configurable"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider">{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {(mapData?.items ?? []).map(i => (
                  <tr key={i.category} className="border-b border-surface-border last:border-0">
                    <td className="px-4 py-3 font-medium text-text-primary">{i.category}</td>
                    <td className="px-4 py-3 text-xs font-mono text-text-secondary">{i.table}</td>
                    <td className="px-4 py-3"><span className={cn("text-xs font-medium", SENS[i.sensitivity])}>{i.sensitivity}</span></td>
                    <td className="px-4 py-3 text-xs text-text-secondary max-w-xs">{i.purpose}</td>
                    <td className="px-4 py-3 text-xs">{i.contains_pii_risk ? <span className="text-status-error">Yes</span> : <span className="text-text-muted">No</span>}</td>
                    <td className="px-4 py-3 text-xs">{i.can_disable ? <span className="text-status-ok">Yes</span> : <span className="text-text-muted">No</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "retention" && policy && (
          <div className="space-y-4">
            <div className="rounded-lg border border-surface-border bg-surface-card p-5">
              <h2 className="mb-4 text-sm font-semibold text-text-primary">Current retention policy</h2>
              <div className="grid grid-cols-2 gap-4">
                {([["Traces", policy.traces_retention_days],["Spans", policy.spans_retention_days],["Audit logs", policy.audit_logs_retention_days],["Cost records", policy.cost_records_retention_days]] as [string,number|null][]).map(([label,val]) => (
                  <div key={label} className="rounded border border-surface-border p-3">
                    <p className="text-xs text-text-muted">{label}</p>
                    <p className="mt-1 text-base font-semibold text-text-primary">{val ? `${val} days` : "Forever"}</p>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <div className={cn("h-2 w-2 rounded-full", policy.anonymize_user_references ? "bg-status-ok" : "bg-text-muted")} />
                <span className="text-xs text-text-secondary">User references {policy.anonymize_user_references ? "are" : "are not"} anonymized automatically</span>
              </div>
            </div>
            <button onClick={() => handleAction("retention")} disabled={submitting}
              className="rounded-md border border-status-error/30 bg-status-error/10 px-4 py-2 text-sm text-status-error hover:bg-status-error/20 disabled:opacity-50 transition-colors">
              {submitting ? "Running…" : "Run retention now"}
            </button>
            {result && <p className="text-sm text-text-secondary">{result}</p>}
          </div>
        )}

        {tab === "requests" && (
          <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-surface-border">
                {["Type","Status","Subject","Notes","Created","Completed"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase">{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {(requests?.items ?? []).length === 0 ? (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-text-muted">No requests yet.</td></tr>
                ) : (requests?.items ?? []).map(r => (
                  <tr key={r.id} className="border-b border-surface-border last:border-0">
                    <td className="px-4 py-3 text-xs font-mono text-text-secondary">{r.type}</td>
                    <td className="px-4 py-3"><span className={cn("text-xs font-medium", STATUS_C[r.status])}>{r.status}</span></td>
                    <td className="px-4 py-3 text-xs font-mono text-text-muted">{r.subject_reference}</td>
                    <td className="px-4 py-3 text-xs text-text-secondary">{r.notes ?? "—"}</td>
                    <td className="px-4 py-3 text-xs text-text-muted">{new Date(r.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3 text-xs text-text-muted">{r.completed_at ? new Date(r.completed_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "actions" && (
          <div className="space-y-6 max-w-lg">
            <div className="rounded-lg border border-surface-border bg-surface-card p-5 space-y-3">
              <h2 className="text-sm font-semibold text-text-primary">Subject reference</h2>
              <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="user_hash_abc123 (never raw PII)"
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none" />
              <div className="grid grid-cols-2 gap-3">
                <button onClick={() => handleAction("export")} disabled={submitting}
                  className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted disabled:opacity-50 transition-colors">Export data</button>
                <button onClick={() => handleAction("anonymize")} disabled={submitting || !subject}
                  className="rounded-md border border-status-warn/30 bg-status-warn/10 px-4 py-2 text-sm text-status-warn hover:bg-status-warn/20 disabled:opacity-50 transition-colors">Anonymize</button>
              </div>
            </div>
            <div className="rounded-lg border border-surface-border bg-surface-card p-5 space-y-3">
              <h2 className="text-sm font-semibold text-text-primary">Create privacy request</h2>
              <select value={reqType} onChange={e => setReqType(e.target.value)}
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:outline-none">
                {["EXPORT","ANONYMIZE","DELETE","ACCESS"].map(t => <option key={t}>{t}</option>)}
              </select>
              <input value={reqNote} onChange={e => setReqNote(e.target.value)} placeholder="Notes (optional)"
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none" />
              <button onClick={() => handleAction("request")} disabled={submitting || !subject}
                className="w-full rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50 transition-colors">Submit request</button>
            </div>
            {result && <div className="rounded-md border border-surface-border bg-surface-card p-3 text-sm text-text-secondary">{result}</div>}
          </div>
        )}
      </div>
    </ProtectedLayout>
  );
}
