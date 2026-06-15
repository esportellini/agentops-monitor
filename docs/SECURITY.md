# Security

## Detection pipeline

All content flowing through the ingest API is scanned by a rule-based engine
before storage. The engine uses regex and structural validation — no LLM involved.

### Detectors

| Type | Method |
|---|---|
| Email | RFC-compliant regex |
| Phone (BR) | DDD + number pattern |
| CPF | Regex + 2-digit checksum |
| Credit card | Card number regex + Luhn algorithm |
| API keys | Known provider prefixes (OpenAI, Anthropic, AWS, GitHub, AgentOps) |
| Bearer tokens | `Authorization: Bearer` pattern |
| Password fields | Key-value pairs with sensitive field names |
| Prompt injection | 10 pattern library (DAN, override, system tags, etc.) |
| Dangerous SQL | DROP, TRUNCATE, DELETE WHERE 1=1, xp_cmdshell |

### Actions per finding

Configurable per agent via `AgentPolicy`:

| Action | Behavior |
|---|---|
| `detect` | Log finding, no other effect |
| `redact` | Replace with placeholder in stored data |
| `alert` | Create AlertIncident + log finding |
| `block` | Reject the span/trace entirely |

## Tool approval workflow

Tools listed in `tools_requiring_approval` create a `ToolApproval` record
with status `pending`. The agent is blocked until an ANALYST+ user approves.

## Multi-tenant isolation

- Every query is scoped by `organization_id`
- Cross-org access attempts are blocked at the dependency layer and logged
- API keys are scoped to a single organization

## Prompt injection

The scanner detects 10 patterns including:
- "ignore all previous instructions"
- "you are now a DAN model"
- XML system tags (`<system>`, `<instructions>`)
- "override your training"
- "jailbreak mode"
