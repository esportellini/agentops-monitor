"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";
import { API_URL } from "@/lib/api";

interface Log { id: number; event_type: string; severity: string; message: string; entity_type: string|null; entity_id: string|null; user_id: number|null; ip_address: string|null; before_data: Record<string,unknown> | null; after_data: Record<string,unknown> | null; created_at: string; }

const SEV: Record<string,string> = { CRITICAL: "text-status-error", HIGH: "text-status-error", MEDIUM: "text-status-warn", LOW: "text-status-ok", INFO: "text-text-muted" };

export default function AuditLogsPage() {
  const { activeOrg, accessToken } = useAuth();
  const fetch = useAuthFetch();
  const [eventType, setEventType] = useState("");
  const [severity, setSeverity] = useState("");
  const [selected, setSelected] = useState<Log|null>(null);

  const params = new URLSearchParams({ limit: "100" });
  if (eventType) params.set("event_type", eventType);
  if (severity) params.set("severity", severity);

  const { data, isLoading } = useQuery<{ total: number; items: Log[] }>({
    queryKey: ["audit-logs", activeOrg?.id, eventType, severity],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/audit-logs?${params}`),
    enabled: !!activeOrg,
  });

  const logs = data?.items ?? [];

  async function exportCsv() {
    if (!activeOrg || !accessToken) return;
    const response = await window.fetch(
      `${API_URL}/api/v1/organizations/${activeOrg.id}/audit-logs/export.csv?${params}`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    if (!response.ok) return;

    const objectUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `audit-logs-${activeOrg.id}.csv`;
    link.click();
    URL.revokeObjectURL(objectUrl);
  }

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Audit Logs</h1>
            <p className="mt-1 text-sm text-text-secondary">{data?.total ?? 0} events · immutable record of all security-relevant actions</p>
          </div>
          <button onClick={exportCsv} className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted transition-colors">
            Export CSV
          </button>
        </div>

        <div className="mb-4 flex gap-3">
          <input value={eventType} onChange={e => setEventType(e.target.value)} placeholder="Filter by event type…"
            className="flex-1 rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none" />
          <select value={severity} onChange={e => setSeverity(e.target.value)}
            className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:outline-none">
            <option value="">All severities</option>
            {["CRITICAL","HIGH","MEDIUM","LOW","INFO"].map(s => <option key={s}>{s}</option>)}
          </select>
          {(eventType||severity) && <button onClick={() => { setEventType(""); setSeverity(""); }} className="text-xs text-text-muted hover:text-text-secondary">Clear</button>}
        </div>

        <div className="rounded-lg border border-surface-border bg-surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-surface-border">
              {["Severity","Event","Message","Entity","User","IP","Time"].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase tracking-wider whitespace-nowrap">{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {isLoading ? <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-text-muted">Loading…</td></tr>
              : logs.length === 0 ? <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-text-muted">No events found.</td></tr>
              : logs.map(log => (
                <tr key={log.id} onClick={() => setSelected(selected?.id === log.id ? null : log)}
                  className="border-b border-surface-border last:border-0 hover:bg-surface-muted/30 cursor-pointer transition-colors">
                  <td className="px-4 py-2.5">
                    <span className={cn("text-xs font-medium", SEV[log.severity] ?? "text-text-muted")}>{log.severity}</span>
                  </td>
                  <td className="px-4 py-2.5 text-xs font-mono text-text-secondary whitespace-nowrap">{log.event_type}</td>
                  <td className="px-4 py-2.5 text-xs text-text-primary max-w-sm truncate">{log.message}</td>
                  <td className="px-4 py-2.5 text-xs text-text-muted">{log.entity_type ? `${log.entity_type}#${log.entity_id}` : "—"}</td>
                  <td className="px-4 py-2.5 text-xs text-text-muted">{log.user_id ? `#${log.user_id}` : "—"}</td>
                  <td className="px-4 py-2.5 text-xs text-text-muted">{log.ip_address ?? "—"}</td>
                  <td className="px-4 py-2.5 text-xs text-text-muted whitespace-nowrap">{new Date(log.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {selected && (
          <div className="mt-4 rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-3 text-sm font-semibold text-text-primary">Event detail — #{selected.id}</h2>
            <div className="grid grid-cols-2 gap-4 text-sm mb-4">
              {[["Event type", selected.event_type], ["Severity", selected.severity], ["Message", selected.message], ["Entity", selected.entity_type ? `${selected.entity_type} #${selected.entity_id}` : "—"]].map(([l,v]) => (
                <div key={l as string}><p className="text-xs text-text-muted">{l}</p><p className="mt-0.5 text-text-primary">{v}</p></div>
              ))}
            </div>
            {selected.before_data && (
              <div className="mb-3">
                <p className="mb-1 text-xs text-text-muted">Before</p>
                <pre className="rounded bg-surface-muted p-2 text-xs text-text-secondary overflow-x-auto">{JSON.stringify(selected.before_data, null, 2)}</pre>
              </div>
            )}
            {selected.after_data && (
              <div>
                <p className="mb-1 text-xs text-text-muted">After</p>
                <pre className="rounded bg-surface-muted p-2 text-xs text-text-secondary overflow-x-auto">{JSON.stringify(selected.after_data, null, 2)}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </ProtectedLayout>
  );
}
