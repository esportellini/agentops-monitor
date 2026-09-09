# Runtime alerts implementation plan

## Goal

Connect security findings and finished traces to tenant-scoped alert rules and durable in-app incidents without making alert evaluation a prerequisite for ingestion.

## Design

- Represent runtime inputs with a typed `RuntimeAlertEvent` carrying safe identifiers and an allowlisted data payload.
- Support `security.finding.created` and `trace.finished` with one explicitly validated condition per rule.
- Add event type and agent scope to rules; add source, scope, severity snapshot, trace provenance, and a deterministic dedupe key to incidents.
- Evaluate only active rules in matching organization, project, and agent scope.
- Run evaluator work behind nested transactions and catch failures so the ingest transaction remains usable.
- Deactivate rules instead of deleting them so incident history remains reachable.
- Model incident handling as `OPEN -> ACKNOWLEDGED -> RESOLVED` or `OPEN -> RESOLVED`, with `RESOLVED` terminal.

## Work

1. Add failing service/API/runtime tests for validation, matching, scope, dedupe, isolation, lifecycle, RBAC, and tenancy.
2. Add migration `0010_runtime_alerts` and update alert models.
3. Replace the alert evaluator with typed events, condition validation, safe incident context, dedupe, audit logs, and structured logs.
4. Wire newly persisted security findings and trace completion into the isolated evaluator.
5. Strengthen rule and incident APIs with typed payloads, filters, detail, deactivation, acknowledge, and resolve operations.
6. Replace `/alerts` with functional Incidents and Rules views using the current design system.
7. Update seed data and documentation to advertise only implemented events and metrics.
8. Run backend, SDK, frontend, Python, Alembic, diff, and security validation; commit and push.

## Supported contract

- Events: `security.finding.created`, `trace.finished`.
- Security metrics: `finding_type`, `severity`, `action_taken`, `event_type`.
- Trace metrics: `trace_status`, `risk_level`, `total_cost_usd`, `total_tokens`, `duration_ms`, `unpriced_model_calls`, `event_type`.
- Operators: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, with explicit type compatibility.

## Constraints

- No raw finding evidence, trace payload, PII, secrets, or tool arguments in incidents, audit records, or evaluator logs.
- No external notifications, workers, queues, schedulers, anomaly detection, provider integrations, redesign, CI, or release work.
