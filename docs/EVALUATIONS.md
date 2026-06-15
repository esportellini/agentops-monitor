# Evaluations

AgentOps Monitor supports offline evaluation of agents using test datasets.
Evaluations are deterministic by default — no LLM required.

## Concepts

- **Dataset** — collection of test cases with inputs and expected outputs
- **Case** — one test input + optional expected output + optional expected tools
- **Run** — execution of a dataset against a provider/model configuration
- **Result** — outcome of one case in a run, with per-evaluator details

## Evaluators

All evaluators are pure Python functions. They never call an external API.

| Evaluator | Config | Description |
|---|---|---|
| `exact_match` | `fields: list` | Field-level equality (or full dict) |
| `word_presence` | `keywords: list` | All keywords must appear in output |
| `json_structure` | `required_keys: list` | Output must have all required keys |
| `expected_tools` | `strict: bool` | Tool calls must match expected set |
| `cost_limit` | `max_cost_usd: float` | Cost must be below threshold |
| `latency_limit` | `max_latency_ms: int` | Latency must be below threshold |
| `required_source` | `sources: list` | At least one source ID must be cited |

## Run configuration

```json
{
  "dataset_id": 1,
  "name": "GPT-4o vs Claude baseline",
  "provider": "mock",
  "model": "gpt-4o",
  "agent_version": "2.1.0",
  "config": {
    "evaluators": [
      { "name": "exact_match", "fields": ["decision"] },
      { "name": "word_presence", "keywords": ["approved", "rejected"] },
      { "name": "cost_limit", "max_cost_usd": 0.01 },
      { "name": "latency_limit", "max_latency_ms": 2000 }
    ]
  }
}
```

## Human review

Each result can be marked `approved`, `rejected`, or `needs_review`
via `POST /organizations/{id}/evaluation-results/{result_id}/human-review`.

## Run comparison

`GET /organizations/{id}/evaluation-runs/compare?run_a=1&run_b=2`

Returns:
- delta pass rate, score, cost, latency
- case IDs that improved (B better than A)
- case IDs that regressed (A better than B)
- cases where both pass / both fail

## Adding real providers

Implement the `MockProvider` interface in `app/services/evaluator.py`:

```python
class OpenAIProvider:
    name = "openai"

    def run(self, case_input: dict, config: dict) -> RunnerOutput:
        # call OpenAI API
        ...
```

Register in `PROVIDERS`:
```python
PROVIDERS["openai"] = OpenAIProvider()
```
