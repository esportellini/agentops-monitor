"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
import { cn } from "@/lib/utils";

type JsonValue = string | number | boolean | null | JsonValue[] | { [k: string]: JsonValue };

interface ToolCall {
  id: number;
  tool_name: string;
  status: string;
  duration_ms: number | null;
  input_data: JsonValue | null;
  output_data: JsonValue | null;
  requires_approval: boolean;
  blocked_reason: string | null;
}
interface ModelCall {
  id: number;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  latency_ms: number | null;
  status: string;
}
interface SpanDetail {
  id: number;
  external_span_id: string | null;
  parent_span_id: number | null;
  name: string;
  type: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  input_data: JsonValue | null;
  output_data: JsonValue | null;
  error_data: JsonValue | null;
  metadata: JsonValue | null;
  tool_calls: ToolCall[];
  model_calls: ModelCall[];
}
interface TraceEvent {
  id: number;
  event_type: string;
  severity: string;
  message: string;
  created_at: string;
  span_id: number | null;
  metadata: JsonValue | null;
}
interface CostRecord {
  provider: string;
  model: string;
  cost_usd: number;
}
interface TraceDetail {
  id: number;
  external_trace_id: string | null;
  name: string;
  status: string;
  risk_level: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost: number;
  spans: SpanDetail[];
  events: TraceEvent[];
  cost_records: CostRecord[];
  metadata: JsonValue | null;
}

const STATUS_DOT: Record<string, string> = {
  RUNNING: "bg-status-info",
  SUCCESS: "bg-status-ok",
  ERROR: "bg-status-error",
  BLOCKED: "bg-status-warn",
};
const SPAN_TYPE_COLOR: Record<string, string> = {
  AGENT: "text-purple-400",
  LLM: "text-brand-500",
  TOOL: "text-yellow-400",
  RETRIEVAL: "text-cyan-400",
  DATABASE: "text-orange-400",
  HTTP: "text-green-400",
  VALIDATION: "text-pink-400",
  CUSTOM: "text-text-muted",
};
const SEV_COLOR: Record<string, string> = {
  INFO: "text-text-muted",
  LOW: "text-status-ok",
  MEDIUM: "text-status-warn",
  HIGH: "text-status-error",
  CRITICAL: "text-status-error font-bold",
};

function fmtDuration(ms: number | null) {
  if (ms == null) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
}

function fmtCost(c: number) {
  return c === 0 ? "—" : `$${c.toFixed(6)}`;
}

function JsonBlock({ value }: { value: JsonValue | null }) {
  if (value == null) return null;
  return (
    <pre className="mt-1 text-xs overflow-x-auto whitespace-pre-wrap break-words">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function buildTree(spans: SpanDetail[]): SpanDetail[] {
  return spans.filter((s) => s.parent_span_id == null);
}

function SpanNode({
  span,
  spans,
  depth = 0,
}: {
  span: SpanDetail;
  spans: SpanDetail[];
  depth?: number;
}) {
  const children = spans.filter((s) => s.parent_span_id === span.id);

  return (
    <div>
      <div
        className="flex items-start gap-2 rounded-md px-3 py-2 hover:bg-surface-muted/50 transition-colors"
        style={{ marginLeft: depth * 20 }}
      >
        <span
          className={cn(
            "text-[10px] font-medium uppercase mt-0.5 shrink-0 w-16",
            SPAN_TYPE_COLOR[span.type],
          )}
        >
          {span.type}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-text-primary truncate">{span.name}</p>
          <div className="flex items-center gap-3 mt-0.5">
            <span
              className={cn(
                "text-xs",
                span.status === "ERROR" ? "text-status-error" : "text-text-muted",
              )}
            >
              {span.status}
            </span>
            <span className="text-xs text-text-muted tabular-nums">
              {fmtDuration(span.duration_ms)}
            </span>
            {span.model_calls.length > 0 && (
              <span className="text-xs text-text-muted">
                {span.model_calls
                  .reduce((a, mc) => a + mc.input_tokens + mc.output_tokens, 0)
                  .toLocaleString()}{" "}
                tokens
              </span>
            )}
          </div>

          {span.error_data != null && (
            <pre className="mt-1 text-xs text-status-error bg-status-error/5 rounded px-2 py-1 overflow-x-auto">
              {JSON.stringify(span.error_data, null, 2)}
            </pre>
          )}

          {span.tool_calls.length > 0 && (
            <div className="mt-2 space-y-1">
              {span.tool_calls.map((tc) => (
                <div key={tc.id} className="flex items-center gap-2 text-xs text-text-muted">
                  <span className="text-yellow-400">⚙</span>
                  <span className="font-mono">{tc.tool_name}</span>
                  <span className={tc.status === "BLOCKED" ? "text-status-error" : ""}>
                    {tc.status}
                  </span>
                  {tc.blocked_reason != null && (
                    <span className="text-status-error">{tc.blocked_reason}</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {span.model_calls.length > 0 && (
            <div className="mt-2 space-y-1">
              {span.model_calls.map((mc) => (
                <div key={mc.id} className="flex items-center gap-3 text-xs text-text-muted">
                  <span className="text-brand-500">◈</span>
                  <span>
                    {mc.provider}/{mc.model}
                  </span>
                  <span className="tabular-nums">
                    ↑{mc.input_tokens} ↓{mc.output_tokens}
                  </span>
                  <span className="tabular-nums">{fmtCost(mc.estimated_cost)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {children.map((child) => (
        <SpanNode key={child.id} span={child} spans={spans} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function TraceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { activeOrg } = useAuth();
  const fetch = useAuthFetch();

  const { data: trace, isLoading } = useQuery<TraceDetail>({
    queryKey: ["trace", id],
    queryFn: () =>
      fetch.get(`/api/v1/organizations/${activeOrg!.id}/traces/${id}`),
    enabled: !!activeOrg,
  });

  if (isLoading)
    return (
      <ProtectedLayout>
        <div className="p-8 text-sm text-text-muted">Loading…</div>
      </ProtectedLayout>
    );
  if (!trace)
    return (
      <ProtectedLayout>
        <div className="p-8 text-sm text-status-error">Trace not found.</div>
      </ProtectedLayout>
    );

  const rootSpans = buildTree(trace.spans);
  const errorSpans = trace.spans.filter((s) => s.status === "ERROR");

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-5xl">
        {/* Breadcrumb */}
        <div className="mb-4 text-xs text-text-muted">
          <Link href="/traces" className="hover:text-text-primary">
            Traces
          </Link>
          {" / "}
          <span className="font-mono">{trace.external_trace_id ?? `#${trace.id}`}</span>
        </div>

        {/* Summary header */}
        <div className="mb-6 rounded-lg border border-surface-border bg-surface-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-lg font-semibold text-text-primary">{trace.name}</h1>
              <p className="mt-0.5 font-mono text-xs text-text-muted">
                {trace.external_trace_id}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  STATUS_DOT[trace.status] ?? "bg-text-muted",
                )}
              />
              <span className="text-sm font-medium text-text-primary">{trace.status}</span>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6 text-sm">
            {(
              [
                ["Duration", fmtDuration(trace.duration_ms)],
                ["Input tokens", trace.total_input_tokens.toLocaleString()],
                ["Output tokens", trace.total_output_tokens.toLocaleString()],
                ["Total cost", fmtCost(trace.total_cost)],
                ["Risk", trace.risk_level],
                ["Spans", trace.spans.length.toString()],
              ] as [string, string][]
            ).map(([label, value]) => (
              <div key={label}>
                <p className="text-xs text-text-muted">{label}</p>
                <p
                  className={cn(
                    "mt-0.5 font-medium tabular-nums",
                    label === "Risk"
                      ? (SEV_COLOR[value] ?? "text-text-primary")
                      : "text-text-primary",
                  )}
                >
                  {value}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-6">
          {/* Errors summary */}
          {errorSpans.length > 0 && (
            <section className="rounded-lg border border-status-error/30 bg-status-error/5 p-4">
              <h2 className="mb-3 text-sm font-semibold text-status-error">
                {errorSpans.length} error{errorSpans.length > 1 ? "s" : ""}
              </h2>
              {errorSpans.map((s) => (
                <div key={s.id} className="text-xs text-text-secondary mb-1">
                  <span className="font-medium text-text-primary">{s.name}</span>
                  {s.error_data != null && (
                    <pre className="mt-1 text-status-error overflow-x-auto">
                      {JSON.stringify(s.error_data, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
            </section>
          )}

          {/* Span tree */}
          <section className="rounded-lg border border-surface-border bg-surface-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">
              Spans ({trace.spans.length})
            </h2>
            {trace.spans.length === 0 ? (
              <p className="text-xs text-text-muted">No spans recorded.</p>
            ) : (
              <div className="space-y-1">
                {rootSpans.map((span) => (
                  <SpanNode key={span.id} span={span} spans={trace.spans} />
                ))}
              </div>
            )}
          </section>

          {/* Events */}
          {trace.events.length > 0 && (
            <section className="rounded-lg border border-surface-border bg-surface-card p-5">
              <h2 className="mb-4 text-sm font-semibold text-text-primary">
                Events ({trace.events.length})
              </h2>
              <div className="space-y-2">
                {trace.events.map((e) => (
                  <div key={e.id} className="flex items-start gap-3 text-xs">
                    <span
                      className={cn(
                        "shrink-0 mt-0.5 font-medium uppercase w-16",
                        SEV_COLOR[e.severity],
                      )}
                    >
                      {e.severity}
                    </span>
                    <span className="text-text-muted shrink-0 font-mono">
                      {new Date(e.created_at).toLocaleTimeString()}
                    </span>
                    <div className="min-w-0">
                      <span className="text-text-secondary font-medium">{e.event_type}</span>
                      <span className="ml-2 text-text-muted">{e.message}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Cost breakdown */}
          {trace.cost_records.length > 0 && (
            <section className="rounded-lg border border-surface-border bg-surface-card p-5">
              <h2 className="mb-4 text-sm font-semibold text-text-primary">Cost breakdown</h2>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-surface-border">
                    {["Provider", "Model", "Cost"].map((h) => (
                      <th key={h} className="pb-2 text-left text-text-muted font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trace.cost_records.map((cr, i) => (
                    <tr key={i} className="border-b border-surface-border/50 last:border-0">
                      <td className="py-2 text-text-secondary">{cr.provider}</td>
                      <td className="py-2 text-text-secondary font-mono">{cr.model}</td>
                      <td className="py-2 text-text-primary tabular-nums">
                        {fmtCost(cr.cost_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {/* Metadata */}
          {trace.metadata != null &&
            typeof trace.metadata === "object" &&
            Object.keys(trace.metadata).length > 0 && (
              <section className="rounded-lg border border-surface-border bg-surface-card p-5">
                <h2 className="mb-3 text-sm font-semibold text-text-primary">Metadata</h2>
                <pre className="text-xs text-text-secondary overflow-x-auto">
                  {JSON.stringify(trace.metadata, null, 2)}
                </pre>
              </section>
            )}
        </div>
      </div>
    </ProtectedLayout>
  );
}
