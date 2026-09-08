# Agent policy engine implementation plan

## Goal

Make `AgentPolicy` authoritative for preflight decisions and ingest-time enforcement while preserving current telemetry contracts and organization isolation.

## Work

1. Add typed policy request/response schemas and a central policy service for active-policy resolution, normalized tool/domain matching, deterministic decisions, security actions, and persisted trace budget state.
2. Add tests for precedence, inactive/no-policy behavior, malformed domains, exact limit boundaries, unpriced-cost uncertainty, and organization/project isolation; expose `POST /ingest/policy/check-tool` using the API-key context and trace-derived agent.
3. Apply policy during ingest: scan before capture suppression, safely replace content for `block`, retain the redaction safety floor, store policy action provenance, detect reported tool violations without changing reported status, and create deduplicated token/cost findings after model calls.
4. Validate and normalize policy CRUD payloads, including agent ownership, actions, arrays, and non-negative limits.
5. Add typed Python SDK decisions/exceptions plus `Span.check_tool()` and `Span.run_tool()` with explicit fail-open/fail-closed behavior and telemetry for blocked, approval-required, unavailable, success, and error outcomes.
6. Add a minimal policy editor to the existing agent detail page and document decision semantics, limits, capture behavior, and SDK use.
7. Run focused tests after each layer, then full backend and SDK suites, frontend typecheck/lint/build, Alembic head checks, and `git diff --check`.

## Constraints

- Do not create approval requests, alerts, providers, workers, or new database state.
- Do not trust `agent_id` from preflight input; derive it from the scoped trace.
- Never persist raw content for a `block` security action.
- Preserve reported post-hoc tool status and express policy violations through findings.
- Treat unpriced model calls as an explicit unknown cost-budget state unless known cost already exceeds the limit.
