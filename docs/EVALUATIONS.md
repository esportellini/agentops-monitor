# Evaluations

AgentOps Monitor owns the complete evaluation domain: datasets, cases, deterministic evaluators, scoring, pass/fail, comparison, human review, and cost attribution. A provider only turns a case input into an actual output.

```text
dataset → provider → normalized output → deterministic evaluators → result → comparison/review
```

## Providers

`mock` is always available and works offline. Its latency and cost are simulated values from the run configuration and results are marked `MOCK`.

`openai` is optional and uses the official asynchronous Python SDK and Responses API. Configure `OPENAI_API_KEY` in the backend environment, select a model ID on each run, and explicitly consent to sending case inputs to the external provider. Credentials never enter the request body, run config, database, frontend, or audit log.

Provider status is available from `GET /organizations/{id}/evaluations/providers`. An unavailable OpenAI provider fails the selected run clearly; it never falls back to mock.

OpenAI receives only a deterministic JSON serialization of `EvaluationCase.input_data`, plus optional plain `instructions`. Expected outputs are retained inside AgentOps for scoring. No tools, web search, file search, function calling, or computer use are configured. Responses are normalized as `{"text":"..."}` in text mode. JSON mode parses a returned JSON object; malformed JSON creates a safe case-level error.

Execution is sequential in the HTTP request. Each provider call has a server-side timeout of 30 seconds and at most two SDK retries by default. Background and large-scale execution remain future work.

## Evaluators

All evaluator configurations are validated before a run starts.

| Evaluator | Required/basic config | Description |
|---|---|---|
| `exact_match` | optional `fields: string[]` | Field equality or full object equality |
| `word_presence` | `keywords: string[]` | Every keyword appears in normalized output |
| `json_structure` | `required_keys: string[]` | Output contains required keys |
| `expected_tools` | optional `strict: boolean` | Tool list matches the case expectation |
| `cost_limit` | `max_cost_usd >= 0` | Case cost stays within the limit |
| `latency_limit` | `max_latency_ms >= 0` | Provider latency stays within the limit |
| `required_source` | `sources: string[]` | At least one source identifier is present |

Skipped evaluators retain compatibility with a passing result and explicitly include `skipped: true` in their details. `cost_limit` fails as indeterminate when real provider pricing is unavailable; an unknown model is never treated as free.

## OpenAI run example

```json
{
  "dataset_id": 1,
  "name": "Responses baseline",
  "provider": "openai",
  "model": "<openai-model-id>",
  "config": {
    "instructions": "Answer concisely.",
    "output_mode": "text",
    "allow_external_provider_data": true,
    "evaluators": [
      {"name": "exact_match", "fields": ["text"]},
      {"name": "cost_limit", "max_cost_usd": 0.01}
    ]
  }
}
```

## Lifecycle and metrics

Only `PENDING` runs may execute. `RUNNING` and `COMPLETED` runs reject another execution, protecting the unique `(run_id, case_id)` invariant. A `FAILED` run records a safe run-level configuration/provider reason. Provider timeout, transient failure, or malformed JSON after execution creates a failed result for that case and later cases continue; the run completes with `error_cases > 0`.

`pass_rate = passed_cases / total_cases`, so provider errors remain visible as case failures. Average score uses cases with evaluator output. Average latency uses calls with a measured duration.

OpenAI token usage resolves through AgentOps `model_pricing` by organization, provider, model, and execution time. Each result stores the pricing row and rate snapshot when found. `PRICED` may legitimately cost zero; `UNPRICED` preserves usage without inventing cost. Run `total_cost` is the known priced total and `unpriced_cases` makes incomplete totals explicit.

## Isolation, comparison, and review

Dataset projects, run datasets, and agents are checked against the active organization. For project-scoped datasets, the optional agent must belong to that same project. Comparisons require both runs in the organization and the same dataset, which keeps case-level improvements and regressions meaningful.

Human review remains independent of deterministic pass/fail. A result can be `approved`, `rejected`, or `needs_review` through `POST /organizations/{id}/evaluation-results/{result_id}/human-review`.
