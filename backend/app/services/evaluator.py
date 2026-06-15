"""
Evaluation engine.

Evaluators are pure functions: (case, result) → EvaluatorResult.
They are deterministic and never call an LLM (unless explicitly the LlmEvaluator).

Evaluator registry maps a string key to an evaluator factory.
A run's config.evaluators list controls which evaluators are applied.

Design:
- ExactMatchEvaluator      — field-level exact equality
- WordPresenceEvaluator    — required keywords present in output
- JsonStructureEvaluator   — output is valid JSON with required keys
- ExpectedToolsEvaluator   — tool calls match expected set
- CostLimitEvaluator       — cost stays under threshold
- LatencyLimitEvaluator    — latency stays under threshold
- LlmEvaluator             — optional, clearly identified, requires explicit opt-in
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import Any

# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class EvaluatorResult:
    name: str
    passed: bool
    score: float            # 0.0 – 1.0
    reason: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class RunnerOutput:
    actual_output: dict
    actual_tools_used: list[str]
    latency_ms: int
    cost: float
    error: str | None = None


# ── Individual evaluators ─────────────────────────────────────────────────────

def exact_match(
    case_input: dict,
    expected: dict | None,
    actual: dict | None,
    config: dict,
) -> EvaluatorResult:
    """Field-level exact equality on specified fields (or full dict)."""
    if expected is None or actual is None:
        return EvaluatorResult("exact_match", passed=True, score=1.0, reason="No expected output — skipped")

    fields = config.get("fields")  # None means compare whole dict
    if fields:
        matches = {f: expected.get(f) == actual.get(f) for f in fields}
        passed = all(matches.values())
        score = sum(1 for v in matches.values() if v) / len(matches)
        return EvaluatorResult("exact_match", passed=passed, score=score,
                               reason=f"Fields matched: {matches}", detail=matches)

    passed = expected == actual
    return EvaluatorResult("exact_match", passed=passed, score=1.0 if passed else 0.0,
                           reason="Full dict match" if passed else "Mismatch")


def word_presence(
    case_input: dict,
    expected: dict | None,
    actual: dict | None,
    config: dict,
) -> EvaluatorResult:
    """All required keywords must appear in the actual output text."""
    keywords: list[str] = config.get("keywords", [])
    if not keywords:
        return EvaluatorResult("word_presence", passed=True, score=1.0, reason="No keywords configured")

    text = json.dumps(actual or {}).lower()
    found = {kw: kw.lower() in text for kw in keywords}
    passed = all(found.values())
    score = sum(1 for v in found.values() if v) / len(found)
    missing = [k for k, v in found.items() if not v]
    return EvaluatorResult(
        "word_presence", passed=passed, score=score,
        reason=f"Missing: {missing}" if missing else "All keywords found",
        detail=found,
    )


def json_structure(
    case_input: dict,
    expected: dict | None,
    actual: dict | None,
    config: dict,
) -> EvaluatorResult:
    """Actual output must be valid JSON with all required_keys present."""
    required_keys: list[str] = config.get("required_keys", [])

    if actual is None:
        return EvaluatorResult("json_structure", passed=False, score=0.0, reason="No output produced")

    missing = [k for k in required_keys if k not in actual]
    passed = not missing
    score = 1.0 - (len(missing) / len(required_keys)) if required_keys else 1.0
    return EvaluatorResult(
        "json_structure", passed=passed, score=score,
        reason=f"Missing keys: {missing}" if missing else "All required keys present",
        detail={"required": required_keys, "missing": missing},
    )


def expected_tools(
    case_input: dict,
    expected_tool_list: list[str] | None,
    actual_tools: list[str],
    config: dict,
) -> EvaluatorResult:
    """All expected tools must appear in actual tool calls."""
    if not expected_tool_list:
        return EvaluatorResult("expected_tools", passed=True, score=1.0, reason="No tools expected")

    actual_set = set(actual_tools or [])
    expected_set = set(expected_tool_list)
    found = expected_set & actual_set
    missing = expected_set - actual_set
    unexpected = actual_set - expected_set if config.get("strict") else set()

    passed = not missing and not unexpected
    score = len(found) / len(expected_set)
    return EvaluatorResult(
        "expected_tools", passed=passed, score=score,
        reason=f"Missing={list(missing)} Unexpected={list(unexpected)}",
        detail={"expected": list(expected_set), "actual": list(actual_set), "missing": list(missing)},
    )


def cost_limit(
    actual_cost: float,
    config: dict,
) -> EvaluatorResult:
    limit = config.get("max_cost_usd", float("inf"))
    passed = actual_cost <= limit
    return EvaluatorResult(
        "cost_limit", passed=passed, score=1.0 if passed else 0.0,
        reason=f"Cost ${actual_cost:.6f} vs limit ${limit:.6f}",
        detail={"actual": actual_cost, "limit": limit},
    )


def latency_limit(
    actual_latency_ms: int,
    config: dict,
) -> EvaluatorResult:
    limit = config.get("max_latency_ms", float("inf"))
    passed = actual_latency_ms <= limit
    return EvaluatorResult(
        "latency_limit", passed=passed, score=1.0 if passed else 0.0,
        reason=f"Latency {actual_latency_ms}ms vs limit {limit}ms",
        detail={"actual": actual_latency_ms, "limit": limit},
    )


def required_source(
    case_input: dict,
    actual: dict | None,
    config: dict,
) -> EvaluatorResult:
    """Output must cite at least one of the required source IDs."""
    required: list[str] = config.get("sources", [])
    if not required or actual is None:
        return EvaluatorResult("required_source", passed=True, score=1.0, reason="No sources required")

    output_text = json.dumps(actual).lower()
    found = [s for s in required if s.lower() in output_text]
    passed = bool(found)
    return EvaluatorResult(
        "required_source", passed=passed, score=1.0 if passed else 0.0,
        reason=f"Found sources: {found}" if found else f"None of {required} cited",
        detail={"required": required, "found": found},
    )


# ── Evaluator pipeline ────────────────────────────────────────────────────────

def run_evaluators(
    case_input: dict,
    expected_output: dict | None,
    expected_tool_list: list[str] | None,
    output: RunnerOutput,
    evaluator_configs: list[dict],
) -> tuple[bool, float, dict]:
    """
    Run all configured evaluators against a single case result.

    Returns:
        (overall_passed, overall_score, detail_dict)
    """
    results: list[EvaluatorResult] = []

    for cfg in evaluator_configs:
        name = cfg.get("name", "")
        try:
            if name == "exact_match":
                results.append(exact_match(case_input, expected_output, output.actual_output, cfg))
            elif name == "word_presence":
                results.append(word_presence(case_input, expected_output, output.actual_output, cfg))
            elif name == "json_structure":
                results.append(json_structure(case_input, expected_output, output.actual_output, cfg))
            elif name == "expected_tools":
                results.append(expected_tools(case_input, expected_tool_list, output.actual_tools_used, cfg))
            elif name == "cost_limit":
                results.append(cost_limit(output.cost, cfg))
            elif name == "latency_limit":
                results.append(latency_limit(output.latency_ms, cfg))
            elif name == "required_source":
                results.append(required_source(case_input, output.actual_output, cfg))
            # llm_evaluator: not implemented here — requires explicit integration
        except Exception as e:
            results.append(EvaluatorResult(name, passed=False, score=0.0, reason=f"Evaluator error: {e}"))

    if not results:
        # No evaluators — pass by default
        return True, 1.0, {}

    overall_passed = all(r.passed for r in results)
    overall_score = sum(r.score for r in results) / len(results)
    detail = {r.name: {"passed": r.passed, "score": r.score, "reason": r.reason, **r.detail}
              for r in results}
    return overall_passed, overall_score, detail


# ── Mock runner ───────────────────────────────────────────────────────────────

class MockProvider:
    """
    Deterministic mock provider for testing.
    Returns a response that echoes the input structure.
    Cost and latency are configurable.

    To add a real provider, implement a class with the same interface:
        async def run(self, case_input: dict, config: dict) -> RunnerOutput
    """

    name = "mock"

    def run(self, case_input: dict, config: dict) -> RunnerOutput:
        latency = config.get("mock_latency_ms", 50)
        cost = config.get("mock_cost", 0.0001)
        error_rate = config.get("mock_error_rate", 0.0)

        if random.random() < error_rate:
            return RunnerOutput(
                actual_output={},
                actual_tools_used=[],
                latency_ms=latency,
                cost=0.0,
                error="Simulated provider error",
            )

        # Echo-based mock output: include the input and simulate a response
        output = {
            "answer": f"Mock response for: {json.dumps(case_input)[:100]}",
            "provider": "mock",
            **config.get("mock_output_override", {}),
        }

        # Simulate tool calls if expected_tools are in input
        tools_used = config.get("mock_tools_called", [])

        return RunnerOutput(
            actual_output=output,
            actual_tools_used=tools_used,
            latency_ms=latency,
            cost=cost,
        )


PROVIDERS: dict[str, Any] = {
    "mock": MockProvider(),
    # "openai": OpenAIProvider(),   # future
    # "anthropic": AnthropicProvider(),  # future
}


def get_provider(name: str) -> Any:
    provider = PROVIDERS.get(name or "mock")
    if provider is None:
        raise ValueError(f"Unknown provider: {name!r}. Available: {list(PROVIDERS)}")
    return provider


# ── Default evaluator config ──────────────────────────────────────────────────

DEFAULT_EVALUATORS = [
    {"name": "exact_match"},
    {"name": "json_structure", "required_keys": []},
]
