# Python SDK

## Installation

```bash
pip install agentops-monitor
```

## Quick start

```python
from agentops_monitor import AgentOps

client = AgentOps(
    api_key="agom_your_key_here",
    endpoint="http://localhost:8000",
    sample_rate=1.0,
    capture_inputs=True,
    capture_outputs=True,
)

with client.trace(name="answer-question") as trace:
    trace.set_input({"question": "Is PETR4 in quiet period?"})

    with trace.span("rag-search", span_type="RETRIEVAL") as span:
        docs = search_documents()
        span.set_output({"num_docs": len(docs)})
        span.add_tool_call("vector_search", input={"q": "PETR4"}, output=docs)

    with trace.span("llm-call", span_type="LLM") as span:
        answer = call_llm(docs)
        span.add_model_call("openai", "gpt-4o",
            input_tokens=500, output_tokens=120)

    trace.set_output({"decision": "pre_approval_required"})

client.flush()
```

The SDK adds `occurred_at` in UTC automatically. The backend calculates the
authoritative cost from versioned pricing. `estimated_cost` remains accepted as
legacy informational input, but it is ignored for persisted cost accounting.

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `api_key` | required | AgentOps API key (`agom_...`) |
| `endpoint` | `http://localhost:8000` | Backend URL |
| `sample_rate` | `1.0` | Fraction of traces to send (0.0–1.0) |
| `capture_inputs` | `True` | Record input data |
| `capture_outputs` | `True` | Record output data |
| `redact_fn` | `None` | `Callable[[Any], Any]` to strip PII before sending |
| `timeout` | `10.0` | HTTP timeout in seconds |
| `disabled` | `False` | No-op mode for tests |

## Redaction

```python
def redact(data):
    if isinstance(data, dict):
        return {k: "***" if k in ("cpf", "email", "senha") else v
                for k, v in data.items()}
    return data

client = AgentOps(api_key="...", redact_fn=redact)
```

## Resilience

The SDK never raises exceptions to your application due to observability failures.
If the backend is unreachable, calls are silently logged and dropped.

## Human approvals

`Span.check_tool()` creates or reuses a one-time approval when policy returns
`REQUIRE_APPROVAL`. `Span.run_tool()` is non-blocking by default and raises
`ApprovalRequiredError` with the approval identity. Set `wait_for_approval=True`
to poll at a bounded interval, revalidate policy after approval, execute once,
and attach `approval_id` to ToolCall telemetry. Rejection, timeout, and approval
service unavailability have distinct typed exceptions and never execute the tool.
