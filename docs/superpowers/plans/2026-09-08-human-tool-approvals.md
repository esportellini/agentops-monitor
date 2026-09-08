# Human tool approvals implementation plan

## Goal

Turn `REQUIRE_APPROVAL` into a one-time, tenant-scoped human approval workflow without weakening policy revalidation or telemetry safety.

## Design

- Add an organization-unique external request ID and `used_at` to `ToolApproval`.
- Add a nullable, unique `approval_id` to `ToolCall`; the uniqueness makes telemetry retries idempotent and limits an approval to one recorded execution.
- Keep deterministic policy evaluation in `services/policy.py` and add `services/approvals.py` as the workflow layer.
- Store only explicitly supplied, structurally sanitized approval context plus a URL stripped of credentials, query, and fragment.
- Use conditional database updates for final reviewer transitions and approval consumption.

## Work

1. Add migration `0009_tool_approval_runtime`, ORM relationships, and ingest schemas.
2. Add backend tests for request creation/reuse, new attempts, pending/approved/rejected states, races, revalidation, scope isolation, consumption, telemetry retry, context redaction, and audit events.
3. Implement approval creation/reuse, safe context, API-key polling, current-policy revalidation, reviewer list/detail/filter/approve/reject APIs, and governance audit events.
4. Validate approved provenance when ingesting a tool call, consume it once, and reuse the existing ToolCall for telemetry retries.
5. Extend the SDK with request IDs, approval metadata, non-blocking errors, bounded polling, re-preflight, rejection/timeout errors, and the rule that fail-open never applies after approval is required.
6. Add `/approvals` with status filters, safe context, notes, approve/reject actions, and navigation.
7. Update README, security, architecture, and SDK documentation.
8. Run full backend, SDK, frontend, Alembic, compile/import, secret, and diff validation; commit and push the completed phase.

## Constraints

- One external request ID represents one tool invocation attempt.
- Approval never bypasses a newer block, domain rule, or trace limit.
- A pending, rejected, timed-out, mismatched, or consumed approval never executes a tool.
- No alerts, notifications, WebSockets, pub/sub, workers, or provider integrations.
