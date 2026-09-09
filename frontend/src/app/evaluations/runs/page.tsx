"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

interface Run { id:number; name:string; provider:string|null; model:string|null; status:string; pass_rate:number|null; average_score:number|null; total_cost:number|null; total_cases:number|null; error_cases:number|null; unpriced_cases:number|null; dataset_id:number; created_at:string; }
interface Dataset { id:number; name:string; project_id:number|null; }
interface Agent { id:number; name:string; project_id:number; version:string; }
interface Provider { id:"mock"|"openai"; available:boolean; message?:string; }

const statusColor: Record<string,string> = { COMPLETED:"text-status-ok", RUNNING:"text-brand-500", FAILED:"text-status-error", PENDING:"text-text-muted" };
const pct = (value:number|null) => value == null ? "—" : `${(value * 100).toFixed(1)}%`;
const usd = (value:number|null) => value == null ? "—" : `$${value.toFixed(4)}`;
const inputClass = "w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-brand-500 focus:outline-none";

export default function RunsPage() {
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();
  const queryClient = useQueryClient();
  const [datasetId, setDatasetId] = useState("");
  const [runName, setRunName] = useState("Evaluation run");
  const [provider, setProvider] = useState<"mock"|"openai">("mock");
  const [model, setModel] = useState("");
  const [agentId, setAgentId] = useState("");
  const [agentVersion, setAgentVersion] = useState("");
  const [promptVersion, setPromptVersion] = useState("");
  const [instructions, setInstructions] = useState("");
  const [outputMode, setOutputMode] = useState<"text"|"json">("text");
  const [consent, setConsent] = useState(false);
  const [evaluators, setEvaluators] = useState('[{"name":"exact_match","fields":["text"]}]');
  const [running, setRunning] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState("");

  const { data: runsData, isLoading } = useQuery<{items:Run[]}>({
    queryKey:["eval-runs", activeOrg?.id],
    queryFn:() => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-runs?limit=50`),
    enabled:!!activeOrg,
  });
  const { data: datasetsData } = useQuery<{items:Dataset[]}>({
    queryKey:["eval-datasets", activeOrg?.id],
    queryFn:() => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluation-datasets`),
    enabled:!!activeOrg,
  });
  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey:["agents", activeOrg?.id],
    queryFn:() => fetch.get(`/api/v1/organizations/${activeOrg!.id}/agents`),
    enabled:!!activeOrg,
  });
  const { data: availability } = useQuery<{providers:Provider[]}>({
    queryKey:["evaluation-providers", activeOrg?.id],
    queryFn:() => fetch.get(`/api/v1/organizations/${activeOrg!.id}/evaluations/providers`),
    enabled:!!activeOrg,
  });

  const datasets = datasetsData?.items ?? [];
  const selectedDataset = datasets.find(item => String(item.id) === datasetId);
  const allowedAgents = agents.filter(item => !selectedDataset?.project_id || item.project_id === selectedDataset.project_id);
  const openAI = availability?.providers.find(item => item.id === "openai");

  async function handleRun() {
    if (!activeOrg || !datasetId) return;
    setFormError("");
    let parsedEvaluators: unknown;
    try {
      parsedEvaluators = JSON.parse(evaluators);
      if (!Array.isArray(parsedEvaluators)) throw new Error();
    } catch {
      setFormError("Evaluators must be a valid JSON array.");
      return;
    }
    setRunning(true);
    try {
      await fetch.post(`/api/v1/organizations/${activeOrg.id}/evaluation-runs`, {
        dataset_id:Number(datasetId), name:runName, provider,
        model:model || null, agent_id:agentId ? Number(agentId) : null,
        agent_version:agentVersion || null, prompt_version:promptVersion || null,
        config:{
          evaluators:parsedEvaluators,
          instructions:provider === "openai" && instructions ? instructions : null,
          output_mode:provider === "openai" ? outputMode : "text",
          allow_external_provider_data:provider === "openai" ? consent : false,
        },
      });
      setShowForm(false);
      setConsent(false);
      await queryClient.invalidateQueries({queryKey:["eval-runs", activeOrg.id]});
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Unable to run evaluation.");
    } finally {
      setRunning(false);
    }
  }

  const submitDisabled = running || !datasetId || (provider === "openai" && (!openAI?.available || !model.trim() || !consent));

  return <ProtectedLayout><div className="p-8 max-w-6xl">
    <div className="mb-6 flex items-center justify-between">
      <div><h1 className="text-xl font-semibold text-text-primary">Evaluation Runs</h1><p className="mt-1 text-sm text-text-secondary">Execute datasets through model providers, then score them with deterministic evaluators</p></div>
      <div className="flex gap-3"><Link href="/evaluations/compare" className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted">Compare</Link><button onClick={() => setShowForm(!showForm)} className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600">+ New run</button></div>
    </div>

    <div className="mb-4 flex gap-3 text-xs">
      <span className="rounded border border-status-ok/30 px-2 py-1 text-status-ok">Mock — available</span>
      <span className={`rounded border px-2 py-1 ${openAI?.available ? "border-status-ok/30 text-status-ok" : "border-surface-border text-text-muted"}`}>OpenAI — {openAI?.available ? "configured" : "not configured"}</span>
    </div>

    {showForm && <div className="mb-6 space-y-4 rounded-lg border border-surface-border bg-surface-card p-5">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="text-xs text-text-muted">Run name<input value={runName} onChange={event => setRunName(event.target.value)} className={`${inputClass} mt-1`} /></label>
        <label className="text-xs text-text-muted">Dataset *<select value={datasetId} onChange={event => {setDatasetId(event.target.value); setAgentId("");}} className={`${inputClass} mt-1`}><option value="">Select dataset…</option>{datasets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="text-xs text-text-muted">Provider<select value={provider} onChange={event => {setProvider(event.target.value as "mock"|"openai"); setConsent(false);}} className={`${inputClass} mt-1`}><option value="mock">Mock — available</option><option value="openai" disabled={openAI?.available === false}>OpenAI — {openAI?.available ? "configured" : "not configured"}</option></select></label>
        <label className="text-xs text-text-muted">Model {provider === "openai" ? "*" : ""}<input value={model} onChange={event => setModel(event.target.value)} placeholder={provider === "openai" ? "<openai-model-id>" : "Optional"} className={`${inputClass} mt-1`} /></label>
        <label className="text-xs text-text-muted">Agent (optional)<select value={agentId} onChange={event => setAgentId(event.target.value)} className={`${inputClass} mt-1`}><option value="">No agent</option>{allowedAgents.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="text-xs text-text-muted">Agent version<input value={agentVersion} onChange={event => setAgentVersion(event.target.value)} className={`${inputClass} mt-1`} /></label>
        <label className="text-xs text-text-muted">Prompt version<input value={promptVersion} onChange={event => setPromptVersion(event.target.value)} className={`${inputClass} mt-1`} /></label>
        {provider === "openai" && <label className="text-xs text-text-muted">Output mode<select value={outputMode} onChange={event => setOutputMode(event.target.value as "text"|"json")} className={`${inputClass} mt-1`}><option value="text">Text</option><option value="json">JSON object</option></select></label>}
      </div>
      {provider === "openai" && <label className="block text-xs text-text-muted">Instructions (optional)<textarea value={instructions} onChange={event => setInstructions(event.target.value)} rows={2} className={`${inputClass} mt-1 resize-y`} /></label>}
      <label className="block text-xs text-text-muted">Evaluators (JSON array)<textarea value={evaluators} onChange={event => setEvaluators(event.target.value)} rows={3} className={`${inputClass} mt-1 font-mono`} /></label>
      {provider === "openai" && <div className="rounded-md border border-status-warn/30 bg-status-warn/5 p-3 text-sm text-text-secondary"><p>This evaluation sends case inputs to the selected external model provider.</p><label className="mt-2 flex items-start gap-2 text-xs text-text-primary"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} className="mt-0.5" />I understand and allow sending this evaluation dataset to the external provider.</label></div>}
      {formError && <p className="text-sm text-status-error">{formError}</p>}
      <div className="flex gap-2"><button onClick={handleRun} disabled={submitDisabled} className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">{running ? "Running…" : "Run evaluation"}</button><button onClick={() => setShowForm(false)} className="rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted">Cancel</button></div>
    </div>}

    <div className="overflow-hidden rounded-lg border border-surface-border bg-surface-card"><table className="w-full text-sm"><thead><tr className="border-b border-surface-border">{["Name","Provider / model","Status","Pass rate","Score","Known cost","Errors","Cases","Date"].map(label => <th key={label} className="whitespace-nowrap px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">{label}</th>)}</tr></thead><tbody>
      {isLoading ? <tr><td colSpan={9} className="px-4 py-8 text-center text-text-muted">Loading…</td></tr> : (runsData?.items ?? []).length === 0 ? <tr><td colSpan={9} className="px-4 py-8 text-center text-text-muted">No runs yet.</td></tr> : (runsData?.items ?? []).map(run => <tr key={run.id} className="border-b border-surface-border last:border-0 hover:bg-surface-muted/30">
        <td className="px-4 py-3"><Link href={`/evaluations/runs/${run.id}`} className="font-medium text-text-primary hover:text-brand-500">{run.name}</Link></td><td className="px-4 py-3 text-xs text-text-secondary">{[run.provider,run.model].filter(Boolean).join(" / ") || "—"}</td><td className={`px-4 py-3 text-xs font-medium ${statusColor[run.status] ?? ""}`}>{run.status}</td><td className="px-4 py-3 tabular-nums">{pct(run.pass_rate)}</td><td className="px-4 py-3 tabular-nums text-text-secondary">{run.average_score?.toFixed(2) ?? "—"}</td><td className="px-4 py-3 tabular-nums text-text-secondary">{usd(run.total_cost)}{run.unpriced_cases ? <span className="block text-[10px] text-status-warn">{run.unpriced_cases} unpriced</span> : null}</td><td className="px-4 py-3 tabular-nums text-text-secondary">{run.error_cases ?? 0}</td><td className="px-4 py-3 tabular-nums text-text-secondary">{run.total_cases ?? "—"}</td><td className="px-4 py-3 text-xs text-text-muted">{new Date(run.created_at).toLocaleDateString()}</td>
      </tr>)}
    </tbody></table></div>
  </div></ProtectedLayout>;
}
