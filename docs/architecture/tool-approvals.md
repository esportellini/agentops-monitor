# One-time tool approval workflow

```text
tool invocation
  → preflight with external_request_id
  → create/reuse pending ToolApproval
  → reviewer approves or rejects (ANALYST+)
  → SDK polls status
  → approved request repeats preflight
  → current policy, domain, token and cost checks
  → execute or block
  → ToolCall.approval_id + ToolApproval.used_at
```

The external request ID belongs to one invocation attempt and remains stable
through HTTP retries, polling, and revalidation. Approval is not permanent for a
tool or trace. The nullable unique `ToolCall.approval_id` provides execution
provenance and makes telemetry retries idempotent.

Reviewer context is opt-in. The backend scans it before storage and strips URL
userinfo, query parameters, and fragments. Audit events record creation, human
decision, and approved execution using identifiers and outcomes only.
