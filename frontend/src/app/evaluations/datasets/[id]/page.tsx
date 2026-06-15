"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

interface Case { id: number; input_data: Record<string,unknown>; expected_output: Record<string,unknown> | null; expected_tools: string[] | null; tags: string[] | null; }
interface Dataset { id: number; name: string; description: string | null; version: string; cases: Case[]; }

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const qc = useQueryClient();
  const [input, setInput] = useState('{"question": ""}');
  const [expected, setExpected] = useState('');
  const [tools, setTools] = useState('');
  const [adding, setAdding] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [jsonError, setJsonError] = useState("");

  const { data: ds, isLoading } = useQuery<Dataset>({
    queryKey: ["eval-dataset", id],
    queryFn: () => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-datasets/${id}`),
    enabled: !!activeOrg,
  });

  async function handleAddCase() {
    if (!activeOrg) return;
    setJsonError("");
    let parsed_input: unknown, parsed_expected: unknown = undefined, parsed_tools: unknown = undefined;
    try { parsed_input = JSON.parse(input); } catch { setJsonError("Input data is not valid JSON"); return; }
    if (expected.trim()) { try { parsed_expected = JSON.parse(expected); } catch { setJsonError("Expected output is not valid JSON"); return; } }
    if (tools.trim()) { try { parsed_tools = JSON.parse(tools); } catch { setJsonError("Expected tools must be a JSON array"); return; } }

    setAdding(true);
    try {
      await fetch.post(`/api/v1/organizations/${activeOrg.id}/evaluation-datasets/${id}/cases`, {
        input_data: parsed_input,
        expected_output: parsed_expected ?? null,
        expected_tools: parsed_tools ?? null,
      });
      setInput('{"question": ""}'); setExpected(""); setTools(""); setShowForm(false);
      qc.invalidateQueries({ queryKey: ["eval-dataset", id] });
    } finally { setAdding(false); }
  }

  if (isLoading) return <ProtectedLayout><div className="p-8 text-sm text-text-muted">Loading…</div></ProtectedLayout>;
  if (!ds) return <ProtectedLayout><div className="p-8 text-sm text-status-error">Dataset not found.</div></ProtectedLayout>;

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-4xl">
        <div className="mb-2 text-xs text-text-muted">
          <Link href="/evaluations/datasets" className="hover:text-text-primary">Datasets</Link>{" / "}<span>{ds.name}</span>
        </div>
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">{ds.name}</h1>
            <p className="text-sm text-text-secondary">v{ds.version} · {ds.cases.length} cases</p>
          </div>
          <button onClick={() => setShowForm(!showForm)} className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 transition-colors">
            + Add case
          </button>
        </div>

        {showForm && (
          <div className="mb-6 rounded-lg border border-surface-border bg-surface-card p-5 space-y-3">
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1">Input data (JSON) *</label>
              <textarea value={input} onChange={e => setInput(e.target.value)} rows={4}
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs font-mono text-text-primary focus:border-brand-500 focus:outline-none resize-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1">Expected output (JSON, optional)</label>
              <textarea value={expected} onChange={e => setExpected(e.target.value)} rows={3}
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs font-mono text-text-primary focus:border-brand-500 focus:outline-none resize-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1">Expected tools (JSON array, optional)</label>
              <input value={tools} onChange={e => setTools(e.target.value)} placeholder='["search", "summarize"]'
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs font-mono text-text-primary focus:border-brand-500 focus:outline-none" />
            </div>
            {jsonError && <p className="text-xs text-status-error">{jsonError}</p>}
            <div className="flex gap-2">
              <button onClick={handleAddCase} disabled={adding}
                className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50 transition-colors">
                {adding ? "Adding…" : "Add case"}
              </button>
              <button onClick={() => setShowForm(false)} className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted transition-colors">Cancel</button>
            </div>
          </div>
        )}

        <div className="space-y-3">
          {ds.cases.length === 0 ? (
            <div className="rounded-lg border border-surface-border bg-surface-card p-8 text-center text-sm text-text-muted">No cases yet. Add one above.</div>
          ) : ds.cases.map((c, i) => (
            <div key={c.id} className="rounded-lg border border-surface-border bg-surface-card p-4">
              <div className="flex items-start justify-between mb-2">
                <span className="text-xs font-medium text-text-muted">Case #{i + 1}</span>
                {c.expected_tools && <span className="text-xs text-text-muted">Tools: {c.expected_tools.join(", ")}</span>}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="mb-1 text-xs font-medium text-text-secondary">Input</p>
                  <pre className="rounded bg-surface-muted p-2 text-xs text-text-secondary overflow-x-auto">{JSON.stringify(c.input_data, null, 2)}</pre>
                </div>
                {c.expected_output && (
                  <div>
                    <p className="mb-1 text-xs font-medium text-text-secondary">Expected output</p>
                    <pre className="rounded bg-surface-muted p-2 text-xs text-text-secondary overflow-x-auto">{JSON.stringify(c.expected_output, null, 2)}</pre>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </ProtectedLayout>
  );
}
