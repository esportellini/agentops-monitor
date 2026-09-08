# Ingestion Security Pipeline Implementation Plan

> **For agentic workers:** Execute inline with strict red-green-refactor cycles. Do not delegate or create commits unless the user explicitly requests it.

**Goal:** Sanitize sensitive ingest payloads before ORM persistence, create safe and deduplicated security findings, aggregate trace risk, validate trace references, and isolate batch items transactionally.

**Architecture:** Preserve the existing regex detectors in `services/security.py`. Add a structural scanner there, and add a focused ingestion-security service that converts matches into safe `SecurityFinding` rows and monotonically raises trace risk. The existing ingest service remains responsible for domain writes and invokes that boundary before assigning content to ORM models. Batch processing wraps each item in a nested transaction.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL, SQLite test dialect, pytest.

**Spec:** `C:/Users/Usuario/.codex/attachments/a8ace649-5326-4b3b-aefb-5260f6313750/pasted-text.txt`

## Global Constraints

- Preserve all baseline changes in the current working tree.
- Never assign raw sensitive content to a persistent ORM field.
- Never write raw sensitive content to findings, logs, exceptions, snapshots, or console output.
- Do not add migrations or infrastructure.
- Do not implement pricing, policy enforcement, approvals, alerts, providers, workers, or UI redesign.
- Keep local backend tests independent of PostgreSQL and Redis while retaining PostgreSQL-compatible SQLAlchemy code.

---

### Task 1: Structured scanner

**Files:**
- Modify: `backend/app/services/security.py`
- Test: `backend/app/tests/test_security.py`

**Interfaces:**
- Produces: `StructuredScanResult(sanitized: Any, matches: list[RuleMatch])`
- Produces: `scan_and_redact_object(obj: Any, field_name: str) -> StructuredScanResult`
- Extends each `RuleMatch.field` with a stable dictionary/list path.

- [ ] Add failing tests for nested dictionaries, lists, multiple matches, scalar values, `None`, preserved structure, redactable categories, and detection-only categories.
- [ ] Run the focused scanner tests and confirm expected failures because the structural API is absent.
- [ ] Implement recursive traversal that calls the existing `scan_text()` only for strings and preserves all other values and container shapes.
- [ ] Run focused and existing security tests.

### Task 2: Safe finding persistence and risk aggregation

**Files:**
- Create: `backend/app/services/ingest_security.py`
- Test: `backend/app/tests/test_ingest_security.py`

**Interfaces:**
- Consumes: structured scan matches, `Trace`, optional `Span`, and optional `agent_id`.
- Produces: safe evidence with field path, finding type, SHA-256 fingerprint, masked preview, and redaction flag.
- Produces: centralized `default_action(match: RuleMatch) -> str` and `persist_findings(...)`.

- [ ] Add failing tests that assert no original email, token, credential, CPF, or card appears in any persisted finding column.
- [ ] Add failing tests for correct organization/trace/span/agent associations and action selection.
- [ ] Add failing tests for logical deduplication and monotonic severity aggregation.
- [ ] Implement safe evidence generation, deduplication query, finding inserts, structured logs, and risk aggregation.
- [ ] Run the focused service tests.

### Task 3: Automatic ingest integration

**Files:**
- Modify: `backend/app/services/ingest.py`
- Test: `backend/app/tests/test_ingest.py`

**Interfaces:**
- Scans: trace start/finish metadata; span create input/output/error/metadata; span update output/error/metadata; tool-call input/output; event message/metadata.
- Persists: sanitized domain records first, flushes IDs, then persists findings in the same transaction.

- [ ] Add failing integration tests for every required ingest field and explicit database-wide absence of a known synthetic secret.
- [ ] Add failing tests that trace start/span retries do not duplicate findings.
- [ ] Add failing tests for risk transitions and trace-finish max-risk behavior.
- [ ] Integrate structured scan results before ORM assignment and persist findings after IDs are available.
- [ ] Run focused ingest and security tests.

### Task 4: Agent and environment isolation

**Files:**
- Modify: `backend/app/services/ingest.py`
- Test: `backend/app/tests/test_ingest.py`

**Interfaces:**
- Produces: project-scoped validation for optional `agent_id` and `environment_id` without revealing foreign tenant existence.

- [ ] Add failing cross-organization and same-organization cross-project tests for both references.
- [ ] Add project-scoped existence queries and safe `403` errors with `ingest.scope_rejected` logs.
- [ ] Run the isolation tests and full ingest file.

### Task 5: Batch savepoint isolation

**Files:**
- Modify: `backend/app/api/ingest.py`
- Test: `backend/app/tests/test_ingest.py`

**Interfaces:**
- Each batch item executes inside `db.begin_nested()`; the request retains one outer commit.

- [ ] Add a failing integration test with valid, real database constraint failure, valid items and assert both valid rows persist.
- [ ] Wrap each item in a nested transaction and explicitly flush before releasing its savepoint.
- [ ] Ensure logged and returned errors expose no payload or database details containing secrets.
- [ ] Run batch tests and the complete backend suite.

### Task 6: Documentation and final verification

**Files:**
- Modify: `docs/SECURITY.md`
- Modify: `README.md` only if its claims about policies or alerts are inaccurate.

**Interfaces:**
- Documents the implemented scan → redact → persist → finding → risk flow and explicitly lists deferred features.

- [ ] Update documentation from verified behavior.
- [ ] Run `pytest app/tests/ -v` from `backend`.
- [ ] Run `pytest tests/ -v` from `sdk-python`.
- [ ] Run frontend lint, TypeScript, and production build.
- [ ] Run `git diff --check` and review every changed file.
- [ ] Report Docker as `NOT RUN — Docker unavailable in environment`.
