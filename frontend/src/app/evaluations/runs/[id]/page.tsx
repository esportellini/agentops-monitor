"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";

interface Result {
  id: number; case_id: number; passed: boolean | null; score: number | null;
  latency_ms: number | null; cost: number | null; actual_output: Record<string,unknown> | null;
  evaluator_details: Record<string,unknown> | null; human_review_status: string | null;
  human_review_note: string | null; error: string | null;
  input_tokens: number|null; output_tokens:number|null; pricing_status:string|null;
}
interface Run {
  id: number; name: string; status: string; provider: string|null; model: string|null;
  pass_rate: number|null; average_score: number|null; total_cost: number|null;
  average_latency_ms: number|null; total_cases: number|null; passed_cases: number|null;
  executed_cases:number|null; error_cases:number|null; unpriced_cases:number|null; failure_reason:string|null;
  results: Result[];
}

const REVIEW_COLORS: Record<string,string> = { approved: "text-status-ok", rejected: "text-status-error", needs_review: "text-status-warn" };

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [reviewing, setReviewing] = useState<number | null>(null);
  const [note, setNote] = useState("");

  const { data: run, isLoading } = useQuery<Run>({
    queryKey: ["eval-run", id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-runs/${id}`),
    enabled: !!activeOrg,
  });

  async function handleReview(resultId: number, status: string) {
    if (!activeOrg) return;
    await fetch.post(`/api/v1/organizations/${activeOrg.id}/evaluation-results/${resultId}/human-review`, { status, note });
    setReviewing(null); setNote("");
    qc.invalidateQueries({ queryKey: ["eval-run", id] });
  }

  if (isLoading) return <ProtectedLayout><div className="p-8 text-sm text-text-muted">Loading…</div></ProtectedLayout>;
  if (!run) return <ProtectedLayout><div className="p-8 text-sm text-status-error">Run not found.</div></ProtectedLayout>;

  const results = run.results ?? [];

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-5xl">
        <div className="mb-2 text-xs text-text-muted">
          <Link href="/evaluations/runs" className="hover:text-text-primary">Runs</Link>{" / "}<span>{run.name}</span>
        </div>
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">{run.name}</h1>
          <p className="text-sm text-text-secondary">{run.provider}{run.model ? ` / ${run.model}` : ""} · Status: <span className={run.status === "COMPLETED" ? "text-status-ok" : "text-text-secondary"}>{run.status}</span></p>
        </div>

        {run.failure_reason && <div className="mb-4 rounded-md border border-status-error/20 bg-status-error/5 p-3 text-sm text-status-error">{run.failure_reason}</div>}

        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-6">
          {[
            ["Pass rate", run.pass_rate != null ? `${(run.pass_rate*100).toFixed(1)}%` : "—"],
            ["Avg score", run.average_score != null ? run.average_score.toFixed(2) : "—"],
            ["Known cost", run.total_cost != null ? `$${run.total_cost.toFixed(4)}` : "—"],
            ["Unpriced", String(run.unpriced_cases ?? 0)],
            ["Avg latency", run.average_latency_ms != null ? `${run.average_latency_ms.toFixed(0)}ms` : "—"],
            ["Cases", `${run.passed_cases ?? 0}/${run.total_cases ?? 0} · ${run.error_cases ?? 0} errors`],
          ].map(([label, val]) => (
            <div key={label as string} className="rounded-lg border border-surface-border bg-surface-card p-3">
              <p className="text-xs text-text-muted">{label}</p>
              <p className="mt-0.5 text-lg font-bold text-text-primary">{val}</p>
            </div>
          ))}
        </div>

        <div className="space-y-3">
          {results.map((r, i) => (
            <div key={r.id} className={cn("rounded-lg border p-4", r.passed ? "border-status-ok/20 bg-status-ok/5" : r.passed === false ? "border-status-error/20 bg-status-error/5" : "border-surface-border bg-surface-card")}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className={cn("text-xs font-bold", r.passed ? "text-status-ok" : r.passed === false ? "text-status-error" : "text-text-muted")}>
                    {r.error ? "PROVIDER ERROR" : r.passed ? "PASS" : r.passed === false ? "FAIL" : "—"}
                  </span>
                  <span className="text-xs text-text-muted">Case #{r.case_id}</span>
                  {r.score != null && <span className="text-xs text-text-secondary">Score: {r.score.toFixed(2)}</span>}
                  {r.latency_ms != null && <span className="text-xs text-text-muted">{r.latency_ms}ms</span>}
                  {r.cost != null && <span className="text-xs text-text-muted">${r.cost.toFixed(5)}</span>}
                  <span className="text-xs text-text-muted">{r.pricing_status ?? "—"}</span>
                  {(r.input_tokens != null || r.output_tokens != null) && <span className="text-xs text-text-muted">{r.input_tokens ?? "?"} in / {r.output_tokens ?? "?"} out</span>}
                </div>
                <div className="flex items-center gap-2">
                  {r.human_review_status && (
                    <span className={cn("text-xs font-medium", REVIEW_COLORS[r.human_review_status] ?? "")}>{r.human_review_status}</span>
                  )}
                  <button onClick={() => setReviewing(reviewing === r.id ? null : r.id)} className="text-xs text-brand-500 hover:underline">Review</button>
                </div>
              </div>

              {r.error && <p className="mt-2 text-xs text-status-error">{r.error}</p>}

              {r.actual_output && (
                <details className="mt-2">
                  <summary className="text-xs text-text-muted cursor-pointer hover:text-text-secondary">Actual output</summary>
                  <pre className="mt-1 rounded bg-surface-muted p-2 text-xs text-text-secondary overflow-x-auto">{JSON.stringify(r.actual_output, null, 2)}</pre>
                </details>
              )}

              {r.evaluator_details && (
                <details className="mt-1">
                  <summary className="text-xs text-text-muted cursor-pointer hover:text-text-secondary">Evaluator details</summary>
                  <pre className="mt-1 rounded bg-surface-muted p-2 text-xs text-text-secondary overflow-x-auto">{JSON.stringify(r.evaluator_details, null, 2)}</pre>
                </details>
              )}

              {reviewing === r.id && (
                <div className="mt-3 space-y-2 border-t border-surface-border pt-3">
                  <textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Review note (optional)…" rows={2}
                    className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-text-primary focus:border-brand-500 focus:outline-none resize-none" />
                  <div className="flex gap-2">
                    <button onClick={() => handleReview(r.id, "approved")} className="rounded px-3 py-1 text-xs font-medium text-white bg-status-ok hover:opacity-90">Approve</button>
                    <button onClick={() => handleReview(r.id, "rejected")} className="rounded px-3 py-1 text-xs font-medium text-white bg-status-error hover:opacity-90">Reject</button>
                    <button onClick={() => handleReview(r.id, "needs_review")} className="rounded px-3 py-1 text-xs font-medium text-status-warn border border-status-warn/30 hover:bg-status-warn/10">Needs review</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </ProtectedLayout>
  );
}
