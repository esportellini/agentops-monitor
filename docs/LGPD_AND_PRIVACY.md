# LGPD and Privacy

## Principles

1. **Data minimization** — inputs/outputs can be disabled per agent policy
2. **Purpose limitation** — data is collected only for observability, never for training
3. **Anonymization by default** — `user_reference` is always a hash, never raw PII
4. **Redaction pipeline** — PII is detected and replaced before storage
5. **Retention limits** — configurable per organization; data is deleted after the window
6. **Subject rights** — export, anonymize, delete, and access requests are tracked

## Data collected

| Category | Sensitivity | PII Risk | Configurable |
|---|---|---|---|
| Traces & Spans | HIGH | Yes | Yes — disable input/output capture |
| Tool calls | HIGH | Yes | Yes |
| Model calls (tokens, cost) | LOW | No | No |
| Security findings | HIGH | Yes | No |
| Audit logs | MEDIUM | Yes | Retention only |
| API key hashes | CRITICAL | No | No — raw key never stored |
| User accounts | HIGH | Yes | No |

## Subject rights (LGPD Art. 18)

Via `POST /organizations/{id}/privacy/requests`:

| Type | Action |
|---|---|
| `ACCESS` | List all data collected for a subject reference |
| `EXPORT` | Download trace data (JSON/CSV) |
| `ANONYMIZE` | Replace user_reference with a hash, null input/output |
| `DELETE` | Delete all traces for a subject (requires manual approval) |

## Retention policy

Configure via `POST /organizations/{id}/privacy/retention-policies`:

```json
{
  "traces_retention_days": 90,
  "spans_retention_days": 90,
  "audit_logs_retention_days": 365,
  "cost_records_retention_days": null,
  "anonymize_user_references": true
}
```

Execute retention: `POST /organizations/{id}/privacy/run-retention`

## What is never stored

- Raw API keys (only bcrypt hash)
- Raw passwords (only bcrypt hash)
- IP addresses in trace data
- PII detected by the security scanner (replaced with `[EMAIL_REDACTED]` etc.)
- Any data used for model training

## Security scanner redaction

The scanner runs on all input/output data before storage and replaces:

| Pattern | Placeholder |
|---|---|
| Email addresses | `[EMAIL_REDACTED]` |
| Brazilian phone numbers | `[PHONE_REDACTED]` |
| CPF (with checksum validation) | `[CPF_REDACTED]` |
| Credit card numbers (Luhn) | `[CARD_REDACTED]` |
| API keys (OpenAI, Anthropic, AWS, GitHub) | `[SECRET_REDACTED]` |
| Bearer tokens | `[TOKEN_REDACTED]` |
