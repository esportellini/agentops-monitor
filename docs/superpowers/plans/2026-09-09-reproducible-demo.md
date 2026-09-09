# Reproducible end-to-end demo plan

1. Add a Docker demo runner that bootstraps all identities and configuration through management APIs and retains its ingest key only in memory.
2. Exercise tracing, backend security redaction, policies, approvals, authoritative pricing, alerts, errors, and mock evaluations through the real SDK/API pipeline.
3. Emit a run-scoped, secret-safe JSON report and fail the process when any required assertion fails.
4. Make the seed restart-safe, document the one-command workflow, and cover runner contracts with unit tests.
5. Run the complete Docker demo with a volume reset and again without reset, then run backend, SDK, frontend, import, migration, and diff checks before commit and push.
