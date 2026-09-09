"""Pure assertions shared by the demo and its no-Docker contract tests."""
from __future__ import annotations

from typing import Any


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def normal_trace(detail: dict[str, Any], incidents: list[dict[str, Any]]) -> None:
    parent = next(x for x in detail["spans"] if x["name"] == "orchestrate")
    child = next(x for x in detail["spans"] if x["name"] == "retrieve")
    model = next(x for x in detail["spans"] if x["name"] == "generate")["model_calls"][0]
    ensure(child["parent_span_id"] == parent["id"], "nested span was not linked")
    ensure(abs(detail["total_cost"] - 0.5) < 1e-9, "authoritative trace cost is not $0.50")
    ensure(model["pricing_status"] == "PRICED" and detail["cost_records"][0]["cost_usd"] == 0.5, "server pricing provenance missing")
    ensure(any(item["event_type"] == "trace.finished" and item["external_trace_id"] == detail["external_trace_id"] for item in incidents), "run-scoped high-cost incident missing")


def security(detail: dict[str, Any], findings: list[dict], incidents: list[dict], raw_values: tuple[str, ...]) -> None:
    persisted = str(detail["spans"][0]["input_data"])
    ensure(all(value not in persisted for value in raw_values), "raw sensitive content persisted")
    types = {x["finding_type"] for x in findings}
    ensure({"pii_email", "bearer_token_detected", "prompt_injection"} <= types, "expected security findings missing")
    ensure(detail["risk_level"] in {"HIGH", "CRITICAL"}, "risk was not aggregated")
    ensure(any(x["event_type"] == "security.finding.created" and x["external_trace_id"] == detail["external_trace_id"] for x in incidents), "run-scoped prompt injection incident missing")


def blocked_side_effect(executed: list, tool: dict[str, Any], reason: str) -> None:
    ensure(not executed and tool["status"] == "BLOCKED" and bool(reason), "blocked side effect executed")


def approval(executed: list, final: dict[str, Any], detail: dict[str, Any], approval_id: int, approved: bool, outcome: str | None) -> None:
    if approved:
        tool = detail["spans"][0]["tool_calls"][0]
        ensure(len(executed) == 1 and final["status"] == "used" and tool["approval_id"] == approval_id, "approved tool execution/linkage invalid")
    else:
        ensure(not executed and outcome == "rejected" and final["status"] == "rejected", "rejected tool executed or exception missing")


def evaluation(baseline: dict[str, Any], candidate: dict[str, Any], comparison: dict[str, Any]) -> None:
    ensure(baseline["status"] == "COMPLETED" and candidate["status"] == "COMPLETED", "evaluation run incomplete")
    ensure(baseline["total_cases"] >= 2 and comparison["delta_pass_rate"] > 0 and len(comparison["improved_cases"]) >= 2, "evaluation comparison was not predictably improved")
