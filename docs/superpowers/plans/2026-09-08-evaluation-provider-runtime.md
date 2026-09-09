# Evaluation Provider Runtime Implementation Plan

**Goal:** Make Evaluations demonstrable offline with the async mock provider and optionally against OpenAI Responses, while preserving AgentOps-owned datasets, evaluators, scoring, comparison, review, and authoritative pricing.

## Backend contracts

1. Extend evaluation run/result persistence with provider provenance, case/error/unpriced aggregates, token usage, pricing status/snapshots, and a unique `(run_id, case_id)` invariant in migration `0011_evaluation_provider_runtime`.
2. Make provider execution async. Keep a small `mock`/`openai` registry, deterministic JSON serialization of case input, Responses API `output_text` normalization, no tools, bounded timeout/retries, and safe error classes.
3. Validate dataset project, run dataset, optional agent/project consistency, provider/model/consent, output mode, and every evaluator config before execution.
4. Enforce `PENDING` as the only executable state. Treat configuration/provider availability as run-level failure and provider failures after start as per-case results so later cases continue.
5. Resolve OpenAI usage through the existing organization-aware pricing service. Persist PRICED/UNPRICED provenance and keep mock cost explicitly simulated.
6. Preserve human review and add safe audit events for dataset/run lifecycle and reviews without case payloads or provider outputs.

## API and UI

1. Add provider availability and typed request validation to the evaluation API.
2. Return the new lifecycle, pricing, and error metrics from run/result/comparison serializers; reject cross-dataset comparison.
3. Update the run form for provider/model/config/evaluators, OpenAI availability, and explicit external-data consent.
4. Update run detail and comparison views for provider errors and incomplete cost reporting.

## Verification

1. Add focused provider, validation, tenant isolation, pricing, idempotency, continuation, no-tools, lifecycle, aggregation, audit, and API tests without network access.
2. Run the complete backend and SDK test suites, frontend lint/typecheck/build, Python import compilation, Alembic head check, secret/data-flow review, and `git diff --check`.
3. Commit `feat: add real evaluation provider runtime`, fetch/reconcile safely, push, and confirm clean synchronized `main`.
