# Changelog

All notable changes to AgentOps Monitor are documented here. The format is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-09-09

### Added

- Automatic security scanning and redaction before ingest persistence.
- Agent policy preflight for tools, domains, data capture, security actions, tokens, and known cost.
- Single-use human approval workflow for governed tool attempts.
- Scoped runtime alert rules, deduplicated incidents, and operational lifecycle actions.
- Evaluation datasets, deterministic evaluators, human review, A/B comparison, and optional OpenAI Responses execution.
- Reproducible Docker demo covering ten linked end-to-end scenarios.
- AI Operations Console interface for observability, governance, FinOps, and evaluation workflows.

### Changed

- Model pricing is authoritative, versioned, effective-dated, and can be overridden per organization.
- The Python SDK records policy and approval provenance while retaining fail-safe observability behavior.
- The frontend now runs on supported Next.js 15.5 LTS and React 19 releases.

### Security

- Sensitive values are replaced before storage and findings retain safe evidence only.
- Next.js and transitive PostCSS dependencies were upgraded to patched releases.
- JWT handling moved to maintained PyJWT, removing the unpatched `ecdsa` dependency.
- FastAPI and Starlette were upgraded to releases that address known 2026 advisories.

## [0.1.0]

- Initial AgentOps Monitor baseline.
