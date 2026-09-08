# AgentOps Monitor v0.2 Baseline Audit Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish an evidence-based v0.2 baseline by mapping the current end-to-end behavior, fixing only reproduced blockers, and reporting the remaining integration gaps.

**Architecture:** Preserve the existing Python SDK, FastAPI/SQLAlchemy backend, PostgreSQL/Redis storage, and Next.js dashboard. Treat code and executable tests as the source of truth, and defer the larger security, pricing, policy, alert, demo, and provider phases.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2 async, PostgreSQL, Redis, Alembic, pytest, Next.js 14, React 18, TypeScript, npm, Docker Compose.

**Spec:** `C:/Users/Usuario/.codex/attachments/8bb4ccc2-ee8c-41a2-b21d-8636dafa7652/pasted-text.txt`

## Global Constraints

- Preserve the current architecture and public APIs unless a reproduced blocker requires a small correction.
- Keep Docker Compose as the local execution model.
- Make database changes only through Alembic; this audit does not plan schema changes.
- Do not implement the seven larger v0.2 phases during this audit.
- Do not add real secrets or visual-only features.

---

### Task 1: Architecture and capability audit

**Files:**
- Inspect: `backend/app/**`, `backend/alembic/**`, `sdk-python/**`, `frontend/src/**`, `examples/demo-agent/**`, and root runtime configuration.
- Produce: final report in the task response.

**Interfaces:**
- Consumes: existing repository at commit `6a36daf`.
- Produces: code-backed feature matrix and the actual SDK-to-dashboard data path.

- [ ] **Step 1: Inventory every tracked source and configuration file**

Run: `rg --files`

Expected: backend, SDK, frontend, migrations, tests, seed, demo, docs, and Compose files are included.

- [ ] **Step 2: Trace the write path**

Inspect SDK transport methods, `/ingest` routes, ingest services, repositories, and trace-related models.

Expected: each persisted field and each unconnected service is identified from call sites.

- [ ] **Step 3: Trace the read path**

Inspect authenticated API v1 routes, frontend fetch helpers, and every dashboard page.

Expected: frontend pages are classified as functional, partial, or placeholder based on their real API use.

### Task 2: Reproduce the baseline

**Files:**
- Test: `backend/app/tests/**`
- Test: `sdk-python/tests/test_sdk.py`
- Verify: `frontend/package.json`
- Verify: `docker-compose.yml`

**Interfaces:**
- Consumes: declared project dependencies and local runtime configuration.
- Produces: exact pass/fail counts and root-cause evidence.

- [ ] **Step 1: Install the Python project in editable mode**

Run: `.venv/Scripts/python.exe -m pip install -r backend/requirements.txt -e './sdk-python[dev]'`

Expected before a packaging fix: failure loading the configured setuptools build backend.

- [ ] **Step 2: Run backend tests**

Run from `backend`: `../.venv/Scripts/python.exe -m pytest app/tests/ -v` with `DATABASE_URL` set to the documented PostgreSQL URL.

Expected: the complete collected suite runs after the SDK can be installed.

- [ ] **Step 3: Run SDK tests**

Run from `sdk-python`: `../.venv/Scripts/python.exe -m pytest tests/ -v`.

Expected before the masking fix: `test_mask_key` fails because the stored eight-character key identifier is not retained.

- [ ] **Step 4: Install and validate the frontend**

Run from `frontend`: `npm install`, `npm run type-check`, `npm run lint`, and `npm run build`.

Expected: record each command's exit code without suppressing failures.

- [ ] **Step 5: Attempt the Docker smoke test**

Run: `docker compose build` and `docker compose up -d`, then inspect health and run the seed if Docker is available.

Expected: PostgreSQL, Redis, backend, and frontend become healthy, or the environment limitation is reported explicitly.

### Task 3: Fix reproduced baseline blockers

**Files:**
- Modify: `sdk-python/pyproject.toml`
- Modify: `sdk-python/agentops_monitor/_utils.py`
- Test: existing editable-install command and `sdk-python/tests/test_sdk.py::test_mask_key`

**Interfaces:**
- Consumes: PEP 517 setuptools backend configuration and the stored API-key prefix convention `agom_` plus eight identifier characters.
- Produces: an installable SDK and logging-safe masking that retains the documented identifier.

- [ ] **Step 1: Preserve the failing installation evidence**

Observed: editable installation fails with `BackendUnavailable: Cannot import 'setuptools.backends.legacy'`.

- [ ] **Step 2: Correct the setuptools build backend**

Change `build-backend` to `setuptools.build_meta:__legacy__`.

- [ ] **Step 3: Verify the editable installation**

Run: `.venv/Scripts/python.exe -m pip install -e './sdk-python[dev]'`.

Expected: exit code 0 and an editable `agentops-monitor` installation.

- [ ] **Step 4: Preserve the failing masking evidence**

Observed: `test_mask_key` expects `abcdefgh` but receives `agom_abc...1234`.

- [ ] **Step 5: Retain the full stored prefix in masked output**

Change `mask_key()` to preserve `agom_` plus the first eight random characters and the last four characters, while hiding the middle.

- [ ] **Step 6: Verify the focused regression and full SDK suite**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_sdk.py::test_mask_key -v`, followed by `../.venv/Scripts/python.exe -m pytest tests/ -v`.

Expected: the focused test and all SDK tests pass.

### Task 4: Final verification and report

**Files:**
- Inspect: `git diff`, all validation outputs, and this plan.
- Produce: final task response.

**Interfaces:**
- Consumes: fresh verification evidence.
- Produces: architecture summary, Working/Partial/Missing matrix, fixed-file list, test results, Docker status, and ordered v0.2 implementation phases.

- [ ] **Step 1: Re-run every available validation command**

Run the complete backend and SDK test suites plus frontend type-check, lint, and build.

Expected: exact counts and any remaining failures are captured from fresh output.

- [ ] **Step 2: Review the final diff**

Run: `git diff --check` and `git diff --stat`.

Expected: only small baseline fixes and this audit plan appear.

- [ ] **Step 3: Report Docker separately from code validation**

If Docker is absent from the host, mark the smoke test blocked rather than inferring a result.

- [ ] **Step 4: Deliver the requested report**

Include Current architecture, Working, Partial, Missing, Bugs fixed, Test results, and the seven-step v0.2 implementation order without implementing those phases.
