# Security

## Implemented ingest pipeline

Every supported content field received by `/ingest` is sanitized before it is assigned to a persistent ORM model:

```text
request payload
  → project, agent and environment scope validation
  → recursive structured scan
  → AgentPolicy security action and capture decision
  → safe domain-record persistence
  → SecurityFinding persistence
  → monotonic Trace.risk_level aggregation
```

The scanner preserves dictionaries, lists, scalar values and nested structure. Findings record the precise field path, such as `input_data.user.email`, without storing the original sensitive value.

### Automatically scanned fields

| Ingest operation | Fields |
|---|---|
| `trace_start` | `metadata` |
| `trace_finish` | `metadata` |
| `span_create` | `input_data`, `output_data`, `error_data`, `metadata` |
| `span_update` | `output_data`, `error_data`, `metadata` |
| `tool_call_create` | `input_data`, `output_data` |
| `trace_event` | `message`, `metadata` |

`user_reference` is treated as the pseudonymous identifier supplied by the caller and is not transformed. Model calls currently contain identifiers and metrics rather than prompt/completion content.

### Detection and default actions

| Finding | Detection | Default action |
|---|---|---|
| Email | Pattern | `redact` → `[EMAIL_REDACTED]` |
| Brazilian phone | DDD and number pattern | `redact` → `[PHONE_REDACTED]` |
| CPF | Pattern and checksum | `redact` → `[CPF_REDACTED]` |
| Card number | Card pattern and Luhn | `redact` → `[CARD_REDACTED]` |
| API keys | OpenAI, Anthropic, AWS, GitHub, AgentOps and generic formats | `redact` → `[SECRET_REDACTED]` |
| Bearer tokens | Authorization bearer pattern | `redact` → `[TOKEN_REDACTED]` |
| Credential fields | Password, secret, token and API-key field names | `redact` → `[SECRET_REDACTED]` |
| Prompt injection | Rule library | `detect`; content remains observable |
| Dangerous SQL | Destructive SQL patterns | `detect`; content remains observable |

An active `AgentPolicy` can select `detect`, `redact`, `alert`, or `block` for
PII, secrets, and prompt injection. `redact` replaces detection-only content
with `[REDACTED_BY_POLICY]`; `block` replaces the complete matching leaf with
`[BLOCKED_BY_POLICY]`. Baseline secret and PII redaction remains a safety floor
for `detect` and `alert`. `alert` records the action on the finding but does not
create an alert incident.

## Tool preflight and trace limits

`POST /ingest/policy/check-tool` is authenticated with the same API key used for
ingest. It resolves the trace inside the key's organization and project scope,
then derives the agent from that trace. The request contains only the external
trace ID, tool name, and optional target URL.

Decisions are `ALLOW`, `BLOCK`, and `REQUIRE_APPROVAL`. Explicit blocks override
allowlists, and a blocked domain or exceeded token/cost limit produces `BLOCK`.
Tools listed for approval return `REQUIRE_APPROVAL` after all blocking checks.
The endpoint reports token and cost limit states from persisted model calls.
Equality is within the limit. Unpriced model calls produce cost state `UNKNOWN`
unless known authoritative cost already exceeds the limit.

Tool calls reported after execution are also evaluated. A violation creates a
deduplicated `tool_unauthorized` or `domain_blocked` finding while preserving the
reported `SUCCESS` or `ERROR` status. Blocked and approval-pending telemetry does
not create a post-hoc violation.

Capture flags are enforced after scanning. This lets the backend detect and
record safe findings while persisting `null` for disabled inputs or outputs.

## Safe findings

Automatic findings are associated with the organization and trace, plus the span and agent when available. Evidence contains only:

- field path;
- finding type;
- SHA-256 fingerprint for correlation;
- masked/redacted preview;
- whether redaction occurred.

Raw PII, credentials, tokens and keys are not copied into `evidence`, `description` or `redacted_content`. Logical deduplication uses organization, trace/span, finding type, field path and fingerprint so idempotent retries do not multiply findings.

Trace risk follows `INFO < LOW < MEDIUM < HIGH < CRITICAL`. New findings can only raise risk, and a lower `risk_level` supplied during trace finish cannot reduce it.

## Tenant isolation and batches

Project ownership is checked against the API-key organization. Optional agent and environment references must belong to the resolved project, including when two projects share an organization. Scope rejection responses do not reveal whether a foreign resource exists.

Each batch item runs inside a SQLAlchemy nested transaction. A constraint failure rolls back that item's savepoint while later valid items continue, followed by one outer commit.

## Not implemented yet

- runtime tool-approval creation and suspension;
- alert evaluation or external dispatch from ingest;
- provider-backed security classification;
- background processing.
