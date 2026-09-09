# Reproducible integrated demo

## Run

From the repository root:

```bash
python scripts/demo.py --reset
```

The command builds and starts PostgreSQL, Redis, the backend and the frontend, waits for HTTP health, then runs a separate demo container. It leaves the dashboard available at [http://localhost:3000](http://localhost:3000). Run `python scripts/demo.py` again to prove that bootstrap is idempotent.

The demo creates a unique `demo_run_id` and validates only records linked to that execution. Projects, agents, environments, policies, pricing, alert rules, evaluation datasets and API keys are resolved or created through management APIs. The generated ingest key remains in memory and is revoked at the end.

## Proven scenarios

- hierarchical traces, successful tool/model calls and dashboard APIs;
- server-side PII, token and prompt-injection handling without an SDK redaction callback;
- policy blocking before a tool side effect;
- automated human approval and rejection, including single execution and ToolCall linkage;
- authoritative server pricing at $0.50 despite a false client estimate;
- trace cost-limit enforcement and its security finding;
- prompt-injection and high-cost incidents;
- deterministic trace and span errors;
- two-case offline mock evaluation with a predictably improved candidate.

Each check prints `PASS` or `FAIL`; any failure produces a nonzero exit status. A secret-safe machine-readable report is written to `.demo/demo-report.json`.

## Optional OpenAI flag

`python scripts/demo.py --with-openai` runs an additional evaluation only when the backend has `OPENAI_API_KEY` configured. Without a key it reports a skip; with a key it sends the demo dataset with explicit external-provider consent. The default demo never calls an external model.

Use `--interactive-approval` to leave the `send_email` simulation pending for a decision in the dashboard. The normal command decides it automatically and remains unattended.

## Troubleshooting

Use `docker compose --project-name agentops-monitor-demo -f docker-compose.yml -f docker-compose.demo.yml --profile demo ps` to inspect container health and add `logs backend` for backend diagnostics. The dedicated Compose project keeps demo volumes separate from other local stacks. Ports 3000, 8000, 5432 and 6379 must be available.
