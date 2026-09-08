# Authoritative Versioned Pricing Implementation Plan

> **Goal:** Make the backend the authoritative source for model-call costs while preserving historical pricing provenance, tenant isolation, and observability for calls without configured pricing.

## Architecture

All cost resolution and Decimal arithmetic live in `app/services/pricing.py`. A model call is normalized, resolved against an organization override or global default at its `occurred_at` instant, and persisted with an explicit `PRICED` or `UNPRICED` status. Every call receives a `CostRecord`, including configured zero-cost and unpriced calls, so reporting can distinguish free usage from missing pricing. Cost records snapshot the rates and effective timestamp used for the calculation.

`ModelCall.estimated_cost` remains for compatibility, but its stored value is always the server result. The client field is ignored. Trace totals sum persisted server values and expose the number of unpriced calls.

## Tasks

1. **Pricing domain tests and service**
   - Add failing tests for normalization, exact temporal boundaries, organization override precedence, zero prices, missing prices, and deterministic Decimal precision.
   - Add a structured pricing-resolution result and centralize normalization, lookup, arithmetic, quantization, and overlap detection.

2. **Persistence and migration**
   - Add nullable `organization_id` to `ModelPricing` for global defaults and organization overrides.
   - Add `occurred_at`, `pricing_status`, and pricing reference fields to model calls.
   - Add pricing status, pricing reference, rate snapshots, and pricing effective timestamp to cost records.
   - Add an unpriced-call aggregate to traces.
   - Create Alembic revision `0008` with a coherent upgrade and downgrade for existing databases.

3. **Authoritative ingestion**
   - Add failing individual and batch ingestion tests that prove client `estimated_cost` cannot control persistence.
   - Resolve the owning organization and temporal price inside the shared `create_model_call()` path.
   - Persist one authoritative cost record per model call, including priced zero-cost and unpriced calls.
   - Aggregate tokens, known costs, and unpriced-call counts when finishing a trace.

4. **Pricing CRUD isolation**
   - Add cross-organization tests for listing and mutation isolation.
   - Make organization endpoints list global defaults plus only that organization's overrides.
   - Make creates organization-scoped and restrict updates to the current organization's overrides.
   - Reject overlapping active windows for the same organization scope, provider, and model.

5. **Metrics and Costs UI**
   - Add API tests showing that cost summaries use server costs and report unpriced calls overall and by model.
   - Extend cost responses with small unpriced counters without redesigning existing payloads.
   - Update the Costs page to display unpriced counts and avoid presenting missing pricing as a real `$0.00` result.

6. **SDK contract**
   - Add an SDK test for automatic UTC `occurred_at` emission.
   - Keep accepting `estimated_cost`, document it as legacy/informational, and send an automatic call timestamp.

7. **Documentation and verification**
   - Update README and relevant docs with the authoritative flow, versioned organization pricing, immutable provenance, unpriced semantics, and demo/default seed disclaimer.
   - Run backend tests, SDK tests, TypeScript, ESLint, Next.js build, and `git diff --check`.
   - Report Docker as unavailable without installing it.
