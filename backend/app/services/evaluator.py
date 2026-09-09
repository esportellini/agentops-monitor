"""Deterministic evaluators and async model providers for evaluation runs."""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from app.core.config import settings

PRICED = "PRICED"
UNPRICED = "UNPRICED"
MOCK = "MOCK"
ERROR = "ERROR"


@dataclass
class EvaluatorResult:
    name: str
    passed: bool
    score: float
    reason: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class RunnerOutput:
    actual_output: dict
    actual_tools_used: list[str]
    latency_ms: int | None
    cost: Decimal | float | None = None
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    pricing_status: str | None = None


@dataclass(frozen=True)
class ProviderContext:
    organization_id: int
    model: str | None


class EvaluationProvider(Protocol):
    name: str

    async def run(self, case_input: dict, config: dict, context: ProviderContext) -> RunnerOutput: ...


class ProviderRunError(ValueError):
    """Safe configuration/request error that invalidates the complete run."""


def exact_match(case_input: dict, expected: dict | None, actual: dict | None, config: dict) -> EvaluatorResult:
    if expected is None or actual is None:
        return EvaluatorResult("exact_match", True, 1.0, "No expected output - skipped", {"skipped": True})
    fields = config.get("fields")
    if fields:
        matches = {name: expected.get(name) == actual.get(name) for name in fields}
        passed = all(matches.values())
        score = sum(matches.values()) / len(matches)
        return EvaluatorResult("exact_match", passed, score, f"Fields matched: {matches}", matches)
    passed = expected == actual
    return EvaluatorResult("exact_match", passed, 1.0 if passed else 0.0, "Full dict match" if passed else "Mismatch")


def word_presence(case_input: dict, expected: dict | None, actual: dict | None, config: dict) -> EvaluatorResult:
    keywords = config.get("keywords", [])
    if not keywords:
        return EvaluatorResult("word_presence", True, 1.0, "No keywords configured", {"skipped": True})
    text = json.dumps(actual or {}, sort_keys=True).lower()
    found = {keyword: keyword.lower() in text for keyword in keywords}
    missing = [keyword for keyword, present in found.items() if not present]
    return EvaluatorResult("word_presence", not missing, sum(found.values()) / len(found), f"Missing: {missing}" if missing else "All keywords found", found)


def json_structure(case_input: dict, expected: dict | None, actual: dict | None, config: dict) -> EvaluatorResult:
    required = config.get("required_keys", [])
    if actual is None:
        return EvaluatorResult("json_structure", False, 0.0, "No output produced")
    missing = [key for key in required if key not in actual]
    score = 1.0 - len(missing) / len(required) if required else 1.0
    return EvaluatorResult("json_structure", not missing, score, f"Missing keys: {missing}" if missing else "All required keys present", {"required": required, "missing": missing})


def expected_tools(case_input: dict, expected_tool_list: list[str] | None, actual_tools: list[str], config: dict) -> EvaluatorResult:
    if not expected_tool_list:
        return EvaluatorResult("expected_tools", True, 1.0, "No tools expected", {"skipped": True})
    actual_set, expected_set = set(actual_tools or []), set(expected_tool_list)
    missing = expected_set - actual_set
    unexpected = actual_set - expected_set if config.get("strict") else set()
    passed = not missing and not unexpected
    return EvaluatorResult("expected_tools", passed, len(expected_set & actual_set) / len(expected_set), f"Missing={sorted(missing)} Unexpected={sorted(unexpected)}", {"expected": sorted(expected_set), "actual": sorted(actual_set), "missing": sorted(missing)})


def cost_limit(actual_cost: Decimal | float | None, config: dict, pricing_status: str | None = MOCK) -> EvaluatorResult:
    limit = Decimal(str(config["max_cost_usd"]))
    if pricing_status == UNPRICED or actual_cost is None:
        return EvaluatorResult("cost_limit", False, 0.0, "Pricing unavailable", {"actual": None, "limit": float(limit), "indeterminate": True})
    actual = Decimal(str(actual_cost))
    passed = actual <= limit
    return EvaluatorResult("cost_limit", passed, 1.0 if passed else 0.0, f"Cost ${actual} vs limit ${limit}", {"actual": float(actual), "limit": float(limit), "pricing_status": pricing_status or MOCK})


def latency_limit(actual_latency_ms: int | None, config: dict) -> EvaluatorResult:
    limit = int(config["max_latency_ms"])
    if actual_latency_ms is None:
        return EvaluatorResult("latency_limit", False, 0.0, "Latency unavailable")
    passed = actual_latency_ms <= limit
    return EvaluatorResult("latency_limit", passed, 1.0 if passed else 0.0, f"Latency {actual_latency_ms}ms vs limit {limit}ms", {"actual": actual_latency_ms, "limit": limit})


def required_source(case_input: dict, actual: dict | None, config: dict) -> EvaluatorResult:
    required = config.get("sources", [])
    if not required:
        return EvaluatorResult("required_source", True, 1.0, "No sources required", {"skipped": True})
    if actual is None:
        return EvaluatorResult("required_source", False, 0.0, "No output produced")
    output_text = json.dumps(actual, sort_keys=True).lower()
    found = [source for source in required if source.lower() in output_text]
    return EvaluatorResult("required_source", bool(found), 1.0 if found else 0.0, f"Found sources: {found}" if found else f"None of {required} cited", {"required": required, "found": found})


EVALUATORS = {"exact_match", "word_presence", "json_structure", "expected_tools", "cost_limit", "latency_limit", "required_source"}


def _string_list(value: Any, field_name: str, *, allow_empty: bool = True) -> None:
    if not isinstance(value, list) or (not allow_empty and not value) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings")


def validate_evaluator_configs(configs: Any) -> list[dict]:
    if not isinstance(configs, list):
        raise ValueError("evaluators must be a list")
    for index, cfg in enumerate(configs):
        if not isinstance(cfg, dict):
            raise ValueError(f"evaluator {index} must be an object")
        name = cfg.get("name")
        if name not in EVALUATORS:
            raise ValueError(f"Unknown evaluator: {name!r}")
        if name == "exact_match" and "fields" in cfg:
            _string_list(cfg["fields"], "exact_match.fields", allow_empty=False)
        elif name == "word_presence":
            _string_list(cfg.get("keywords"), "word_presence.keywords", allow_empty=False)
        elif name == "json_structure":
            _string_list(cfg.get("required_keys"), "json_structure.required_keys")
        elif name == "expected_tools" and "strict" in cfg and not isinstance(cfg["strict"], bool):
            raise ValueError("expected_tools.strict must be a boolean")
        elif name == "cost_limit":
            value = cfg.get("max_cost_usd")
            try:
                if isinstance(value, bool) or Decimal(str(value)) < 0:
                    raise ValueError
            except Exception as exc:
                raise ValueError("cost_limit.max_cost_usd must be a non-negative number") from exc
        elif name == "latency_limit":
            value = cfg.get("max_latency_ms")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("latency_limit.max_latency_ms must be a non-negative integer")
        elif name == "required_source":
            _string_list(cfg.get("sources"), "required_source.sources", allow_empty=False)
    return configs


def run_evaluators(case_input: dict, expected_output: dict | None, expected_tool_list: list[str] | None, output: RunnerOutput, evaluator_configs: list[dict]) -> tuple[bool, float, dict]:
    results: list[EvaluatorResult] = []
    for cfg in evaluator_configs:
        name = cfg["name"]
        if name == "exact_match":
            result = exact_match(case_input, expected_output, output.actual_output, cfg)
        elif name == "word_presence":
            result = word_presence(case_input, expected_output, output.actual_output, cfg)
        elif name == "json_structure":
            result = json_structure(case_input, expected_output, output.actual_output, cfg)
        elif name == "expected_tools":
            result = expected_tools(case_input, expected_tool_list, output.actual_tools_used, cfg)
        elif name == "cost_limit":
            result = cost_limit(output.cost, cfg, output.pricing_status)
        elif name == "latency_limit":
            result = latency_limit(output.latency_ms, cfg)
        else:
            result = required_source(case_input, output.actual_output, cfg)
        results.append(result)
    if not results:
        return True, 1.0, {}
    return all(result.passed for result in results), sum(result.score for result in results) / len(results), {result.name: {"passed": result.passed, "score": result.score, "reason": result.reason, **result.detail} for result in results}


class MockProvider:
    name = "mock"

    async def run(self, case_input: dict, config: dict, context: ProviderContext) -> RunnerOutput:
        latency = int(config.get("mock_latency_ms", 50))
        cost = Decimal(str(config.get("mock_cost", "0.0001")))
        if random.random() < float(config.get("mock_error_rate", 0.0)):
            return RunnerOutput({}, [], latency, Decimal("0"), "Simulated provider error", pricing_status=MOCK)
        output = {"answer": f"Mock response for: {json.dumps(case_input, sort_keys=True)[:100]}", "provider": "mock", **config.get("mock_output_override", {})}
        return RunnerOutput(output, list(config.get("mock_tools_called", [])), latency, cost, pricing_status=MOCK)


def _safe_provider_failure(exc: Exception) -> tuple[str, bool]:
    name = type(exc).__name__.lower()
    status = getattr(exc, "status_code", None)
    if status in (401, 403) or "authentication" in name or "permission" in name:
        return "Provider authentication failed", True
    if status == 400 or "badrequest" in name or "unprocessable" in name:
        return "Provider rejected model or request", True
    if "timeout" in name:
        return "Provider request timed out", False
    if status == 429 or "ratelimit" in name or "connection" in name or (isinstance(status, int) and status >= 500):
        return "Provider temporarily unavailable", False
    return "Provider execution failed", False


class OpenAIProvider:
    name = "openai"

    def __init__(self, client: Any | None = None):
        if client is None:
            if not settings.openai_api_key:
                raise ProviderRunError("OpenAI provider is not configured")
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds, max_retries=settings.openai_max_retries)
        self.client = client

    async def run(self, case_input: dict, config: dict, context: ProviderContext) -> RunnerOutput:
        started = time.perf_counter()
        request: dict[str, Any] = {
            "model": context.model,
            "input": json.dumps(case_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            "store": False,
        }
        if config.get("instructions"):
            request["instructions"] = config["instructions"]
        try:
            response = await self.client.responses.create(**request)
        except Exception as exc:
            message, run_level = _safe_provider_failure(exc)
            if run_level:
                raise ProviderRunError(message) from None
            return RunnerOutput({}, [], int((time.perf_counter() - started) * 1000), error=message, pricing_status=ERROR)
        latency = int((time.perf_counter() - started) * 1000)
        text = response.output_text or ""
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None
        if config.get("output_mode", "text") == "json":
            try:
                parsed = json.loads(text)
            except (TypeError, json.JSONDecodeError):
                return RunnerOutput({}, [], latency, error="Provider returned invalid JSON", input_tokens=input_tokens, output_tokens=output_tokens, pricing_status=ERROR)
            if not isinstance(parsed, dict):
                return RunnerOutput({}, [], latency, error="Provider JSON output must be an object", input_tokens=input_tokens, output_tokens=output_tokens, pricing_status=ERROR)
            actual = parsed
        else:
            actual = {"text": text}
        return RunnerOutput(actual, [], latency, input_tokens=input_tokens, output_tokens=output_tokens)


PROVIDERS = {"mock": MockProvider, "openai": OpenAIProvider}


def provider_availability() -> list[dict]:
    return [
        {"id": "mock", "available": True},
        {"id": "openai", "available": bool(settings.openai_api_key), **({"message": "OPENAI_API_KEY is not configured"} if not settings.openai_api_key else {})},
    ]


def get_provider(name: str) -> EvaluationProvider:
    factory = PROVIDERS.get(name or "mock")
    if factory is None:
        raise ProviderRunError(f"Unknown provider: {name!r}")
    return factory()


DEFAULT_EVALUATORS = [{"name": "exact_match"}, {"name": "json_structure", "required_keys": []}]
