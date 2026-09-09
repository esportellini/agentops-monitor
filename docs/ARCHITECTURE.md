# Architecture

AgentOps Monitor is a multi-tenant B2B SaaS observability platform for AI agents.

## Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI 0.115 + Python 3.12 |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Database | PostgreSQL 15 |
| Cache / Sessions | Redis 7 |
| Frontend | Next.js 14.2 + TypeScript + Tailwind CSS |
| State | TanStack Query v5 |
| Auth | JWT (access 30 min + refresh 7 days via Redis) |
| Container | Docker + Docker Compose |

## Service topology

```
Browser (localhost:3000)
  │
  ├── Next.js frontend (static + SSR)
  │
  └── Backend API (localhost:8000)
        ├── /api/v1/*     — authenticated REST API
        ├── /ingest/*     — API key authenticated ingest
        └── /health       — health check
              │
              ├── PostgreSQL (port 5432)
              └── Redis (port 6379)
```

## Evaluation flow

```text
EvaluationDataset / EvaluationCase
        ↓ tenant and config validation
Async provider (mock or optional OpenAI Responses)
        ↓ normalized dict output + usage + monotonic latency
AgentOps authoritative pricing
        ↓ PRICED / UNPRICED / MOCK provenance
Deterministic evaluators
        ↓
EvaluationResult → run aggregation → same-dataset comparison → human review
```

Provider execution is sequential and remains inside the HTTP request in v0.2. OpenAI credentials exist only in backend settings. Expected outputs stay inside AgentOps, external-data consent is mandatory, and no provider tools are configured.

## Multi-tenancy

Every resource is scoped to an `organization_id`. The RBAC system enforces:
- `VIEWER` — read-only
- `ANALYST` — read + export + privacy requests
- `DEVELOPER` — create/edit agents, projects, API keys
- `ADMIN` — full control except ownership transfer
- `OWNER` — full control

Cross-org access attempts are logged to `audit_logs` with severity HIGH.

## Data flow

```
Agent (SDK) → POST /ingest/traces/start
            → POST /ingest/traces/{id}/spans
            → POST /ingest/spans/{id}/model-calls
            → POST /ingest/traces/{id}/finish
                    │
                    ├── Security scanner (regex, no AI)
                    ├── Cost calculation (model_pricing table)
                    ├── Runtime events (finding created / trace finished)
                    ├── Scoped alert rule evaluation in savepoints
                    ├── Deduplicated in-app alert incidents
                    └── Stored in PostgreSQL
```
