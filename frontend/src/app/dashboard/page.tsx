"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, LoaderCircle, RotateCcw, ShieldAlert } from "lucide-react";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { formatCost, formatDuration, formatPercentage, formatTokens } from "@/lib/utils";

interface Overview { executions_total:number; executions_today:number; success_rate:number; errors:number; blocked:number; avg_latency_ms:number; total_input_tokens:number; total_output_tokens:number; cost_today_usd:number; cost_mtd_usd:number; cost_projection_usd:number; active_agents:number }
interface Series { bucket:string; executions:number; success:number; errors:number; success_rate:number; avg_latency_ms:number; cost_usd:number }
interface AgentMetric { agent_id:number; agent_name:string; executions:number; success_rate:number; total_cost_usd:number; avg_cost_per_execution_usd:number }
interface Trace { id:number; name:string; external_trace_id:string|null; status:string; risk_level:string; started_at:string; duration_ms:number|null; total_cost:number; total_input_tokens:number; total_output_tokens:number }
interface CostSummary { unpriced_model_calls:number }

const tooltipStyle = { background:"#15191f", border:"1px solid rgba(255,255,255,.12)", borderRadius:7, fontSize:11, boxShadow:"0 12px 30px rgba(0,0,0,.35)" };
function Metric({ label, value, detail }:{ label:string; value:string; detail:string }) { return <div className="overview-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>; }
function PanelState({ loading, error, onRetry, empty }:{ loading:boolean; error:boolean; onRetry:()=>void; empty:string }) {
  if (loading) return <div className="chart-empty" role="status"><LoaderCircle className="spin" size={16}/>Loading current data…</div>;
  if (error) return <div className="chart-empty query-inline" role="alert"><span>Data could not be loaded.</span><button onClick={onRetry}><RotateCcw size={13}/>Retry</button></div>;
  return <div className="chart-empty">{empty}</div>;
}

export default function DashboardPage() {
  const { activeOrg } = useAuth();
  const api = useAuthFetch();
  const base = `/api/v1/organizations/${activeOrg?.id}`;
  const live = { enabled:!!activeOrg, refetchInterval:30000 };
  const overview = useQuery<Overview>({ queryKey:["overview",activeOrg?.id], queryFn:()=>api.get(`${base}/metrics/overview`), ...live });
  const series = useQuery<Series[]>({ queryKey:["timeseries",activeOrg?.id], queryFn:()=>api.get(`${base}/metrics/timeseries?days=30`), ...live });
  const agents = useQuery<AgentMetric[]>({ queryKey:["agent-metrics",activeOrg?.id], queryFn:()=>api.get(`${base}/metrics/agents?days=30`), ...live });
  const traces = useQuery<{items:Trace[]}>({ queryKey:["overview-traces",activeOrg?.id], queryFn:()=>api.get(`${base}/traces?limit=6`), ...live });
  const approvals = useQuery<{items:unknown[]}>({ queryKey:["overview-approvals",activeOrg?.id], queryFn:()=>api.get(`${base}/tool-approvals?status=pending`), ...live });
  const security = useQuery<{unresolved_total:number;by_severity:Record<string,number>}>({ queryKey:["overview-security",activeOrg?.id], queryFn:()=>api.get(`${base}/security/overview`), ...live });
  const costs = useQuery<CostSummary>({ queryKey:["overview-cost-completeness",activeOrg?.id], queryFn:()=>{ const until=new Date().toISOString(); const since=new Date(Date.now()-30*86400000).toISOString(); return api.get(`${base}/costs?since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}`); }, ...live });
  const ov = overview.data;
  const attentionQueries = [approvals, security, costs];
  const attentionBusy = attentionQueries.some(query=>query.isLoading);
  const attentionFailed = attentionQueries.some(query=>query.isError);
  const overviewUnavailable = overview.isLoading || overview.isError;
  const attention = [
    { label:"Pending approvals", value:approvals.data?.items.length??0, href:"/approvals", icon:Clock3, tone:"warning" },
    { label:"Critical or high findings", value:(security.data?.by_severity?.CRITICAL??0)+(security.data?.by_severity?.HIGH??0), href:"/security", icon:ShieldAlert, tone:"danger" },
    { label:"Unpriced model calls", value:costs.data?.unpriced_model_calls??0, href:"/costs", icon:AlertTriangle, tone:"warning" },
  ];

  return <ProtectedLayout><div className="overview-page">
    <header className="page-heading"><div><h1>Operations overview</h1><p>Health, risk, and spend across the last 30 days.</p></div><span className="live-indicator"><i/>Refreshing every 30s</span></header>
    {overview.isError && <div className="query-error" role="alert"><span>Overview metrics could not be loaded.</span><button onClick={()=>void overview.refetch()}>Retry</button></div>}
    <section className="metrics-strip" aria-label="Primary health metrics" aria-busy={overview.isLoading}>
      <Metric label="Executions today" value={overviewUnavailable?"—":(ov?.executions_today??0).toLocaleString()} detail={overview.isError?"Current data unavailable":overview.isLoading?"Loading current data":`${(ov?.executions_total??0).toLocaleString()} in period`}/>
      <Metric label="Success rate" value={overviewUnavailable?"—":formatPercentage(ov?.success_rate)} detail={overview.isError?"Current data unavailable":overview.isLoading?"Loading current data":`${ov?.errors??0} errors · ${ov?.blocked??0} blocked`}/>
      <Metric label="Known cost" value={overviewUnavailable?"—":formatCost(ov?.cost_mtd_usd)} detail={overview.isError?"Current data unavailable":overview.isLoading?"Loading current data":`${formatCost(ov?.cost_today_usd)} today`}/>
      <Metric label="Average latency" value={overviewUnavailable?"—":formatDuration(ov?.avg_latency_ms)} detail={overview.isError?"Current data unavailable":overview.isLoading?"Loading current data":"completed executions"}/>
      <Metric label="Active agents" value={overviewUnavailable?"—":(ov?.active_agents??0).toLocaleString()} detail={overview.isError?"Current data unavailable":overview.isLoading?"Loading current data":`${formatTokens((ov?.total_input_tokens??0)+(ov?.total_output_tokens??0))} tokens`}/>
    </section>
    <div className="overview-grid">
      <section className="ops-panel attention-panel"><div className="panel-heading"><div><h2>Needs attention</h2><p>Current queues and data completeness.</p></div></div>{attentionBusy||attentionFailed ? <PanelState loading={attentionBusy} error={attentionFailed} onRetry={()=>attentionQueries.forEach(query=>void query.refetch())} empty=""/> : <div className="attention-list">{attention.map(({label,value,href,icon:Icon,tone})=><Link href={href} key={label} className={`attention-row ${tone}`}><Icon size={17}/><span><strong>{label}</strong><small>{value===0?"No action required":`${value} ${value===1?"item":"items"}`}</small></span><b>{value}</b><ArrowRight size={15}/></Link>)}</div>}</section>
      <section className="ops-panel trend-panel"><div className="panel-heading"><div><h2>Execution volume</h2><p>Daily executions and failures.</p></div></div>{series.isError&&series.data?.length&&<div className="chart-stale" role="alert">Refresh failed; showing last known data.<button onClick={()=>void series.refetch()}>Retry</button></div>}<div className="chart-frame">{series.data?.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={series.data}><defs><linearGradient id="executionFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#7c6ff2" stopOpacity={.32}/><stop offset="1" stopColor="#7c6ff2" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="rgba(255,255,255,.05)" vertical={false}/><XAxis dataKey="bucket" tickFormatter={v=>new Date(v).toLocaleDateString(undefined,{month:"short",day:"numeric"})} tick={{fill:"#858e9d",fontSize:10}} tickLine={false} axisLine={false}/><YAxis tick={{fill:"#858e9d",fontSize:10}} tickLine={false} axisLine={false} width={30}/><Tooltip contentStyle={tooltipStyle}/><Area type="monotone" dataKey="executions" stroke="#9187ff" strokeWidth={2} fill="url(#executionFill)"/><Area type="monotone" dataKey="errors" stroke="#e0646c" fill="transparent"/></AreaChart></ResponsiveContainer> : <PanelState loading={series.isLoading} error={series.isError} onRetry={()=>void series.refetch()} empty="No execution data in this period."/>}</div></section>
      <section className="ops-panel cost-trend"><div className="panel-heading"><div><h2>Known cost trend</h2><p>Authoritatively priced spend by day.</p></div><Link href="/costs">Open FinOps <ArrowRight size={13}/></Link></div>{series.isError&&series.data?.length&&<div className="chart-stale" role="alert">Refresh failed; showing last known data.<button onClick={()=>void series.refetch()}>Retry</button></div>}<div className="chart-frame">{series.data?.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={series.data}><CartesianGrid stroke="rgba(255,255,255,.05)" vertical={false}/><XAxis dataKey="bucket" hide/><YAxis hide/><Tooltip contentStyle={tooltipStyle} formatter={(v:number)=>formatCost(v)}/><Area type="monotone" dataKey="cost_usd" stroke="#7c6ff2" strokeWidth={2} fill="rgba(124,111,242,.1)"/></AreaChart></ResponsiveContainer> : <PanelState loading={series.isLoading} error={series.isError} onRetry={()=>void series.refetch()} empty="No priced usage in this period."/>}</div></section>
      <section className="ops-panel drivers-panel"><div className="panel-heading"><div><h2>Cost drivers</h2><p>Agents by known spend.</p></div></div>{agents.isError&&agents.data?.length&&<div className="chart-stale" role="alert">Refresh failed; showing last known data.<button onClick={()=>void agents.refetch()}>Retry</button></div>}<div className="chart-frame">{agents.data?.length ? <ResponsiveContainer width="100%" height="100%"><BarChart data={agents.data.slice(0,6)} layout="vertical"><XAxis type="number" hide/><YAxis type="category" dataKey="agent_name" width={96} tick={{fill:"#a4abb8",fontSize:10}} tickLine={false} axisLine={false}/><Tooltip contentStyle={tooltipStyle} formatter={(v:number)=>formatCost(v)}/><Bar dataKey="total_cost_usd" fill="#7c6ff2" radius={[0,3,3,0]} barSize={9}/></BarChart></ResponsiveContainer> : <PanelState loading={agents.isLoading} error={agents.isError} onRetry={()=>void agents.refetch()} empty="No agent cost data."/>}</div></section>
    </div>
    <section className="ops-panel recent-panel"><div className="panel-heading"><div><h2>Recent traces</h2><p>Latest execution activity.</p></div><Link href="/traces">View all traces <ArrowRight size={13}/></Link></div>{traces.isLoading||traces.isError ? <div className="recent-state"><PanelState loading={traces.isLoading} error={traces.isError} onRetry={()=>void traces.refetch()} empty=""/></div> : <div className="table-scroll"><table><thead><tr><th>Trace</th><th>Status</th><th>Risk</th><th>Duration</th><th>Tokens</th><th>Known cost</th><th>Started</th></tr></thead><tbody>{traces.data?.items.map(t=><tr key={t.id}><td><Link href={`/traces/${t.id}`} className="trace-link"><strong>{t.name}</strong><small>{t.external_trace_id??`#${t.id}`}</small></Link></td><td><StatusBadge status={t.status}/></td><td><StatusBadge status={t.risk_level}/></td><td className="font-mono tabular-nums">{formatDuration(t.duration_ms)}</td><td className="font-mono tabular-nums">{formatTokens(t.total_input_tokens+t.total_output_tokens)}</td><td className="font-mono tabular-nums">{formatCost(t.total_cost)}</td><td className="text-text-muted">{new Date(t.started_at).toLocaleString()}</td></tr>)}</tbody></table>{!traces.data?.items.length&&<div className="empty-row"><CheckCircle2 size={18}/>No traces yet. Run the demo or instrument an agent.</div>}</div>}</section>
  </div></ProtectedLayout>;
}
