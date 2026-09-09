# Runtime alerts

```text
SecurityFinding created ─┐
                         ├─ RuntimeAlertEvent ─ AlertRule ─ AlertIncident
Trace finished ──────────┘                         │              │
                                      org/project/agent     acknowledge/resolve
```

## Events and metrics

| Event | Metrics |
|---|---|
| `security.finding.created` | `event_type`, `finding_type`, `severity`, `action_taken` |
| `trace.finished` | `event_type`, `trace_status`, `risk_level`, `total_cost_usd`, `total_tokens`, `duration_ms`, `unpriced_model_calls` |

Conditions use one allowlisted metric and one of `eq`, `neq`, `gt`, `gte`, `lt`,
`lte`, `in`, or `not_in`. Ordered comparisons require numeric metrics. Rules are
validated when created or updated, including event compatibility and project or
agent tenancy. Legacy `cost_usd`, `token_count`, `latency_ms`, and `threshold`
inputs are normalized to the current contract.

## Provenance and safety

Each incident snapshots rule severity and stores event/source identifiers,
trace/project/agent references, and a small condition result. Its deterministic
dedupe key combines rule, event type, source type, and source ID. A retry of the
same source produces the same incident; a new finding or trace remains distinct.

The runtime event contains only allowlisted metrics. It never contains finding
evidence, trace or span payloads, tool arguments, PII, or secrets. Evaluation and
incident writes run behind savepoints and never commit independently, so failure
does not block the primary ingest transaction.

Rules with incident history are deactivated instead of hard-deleted. Incidents
move from `OPEN` to `ACKNOWLEDGED` and then `RESOLVED`, or directly from `OPEN` to
`RESOLVED`. Resolution is terminal. Members can read incidents; `ANALYST+` can
manage rules and incident transitions.

AgentOps v0.2 provides in-app incidents. Slack, email, webhooks, and other
external notification channels are not implemented.
