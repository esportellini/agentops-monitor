"""
Span: a single unit of work within a trace.

Usage:
    with trace.span("search-docs", span_type="retrieval") as span:
        docs = do_search()
        span.set_output(docs)
        span.add_tool_call("vector_search", input={"q": "..."}, output=docs, status="SUCCESS")
"""
from __future__ import annotations

import traceback
import time
from typing import TYPE_CHECKING, Any

from agentops_monitor._utils import new_id, safe_json, utcnow_iso
from agentops_monitor.policy import (
    ApprovalRequiredError,
    PolicyBlockedError,
    PolicyDecision,
    PolicyUnavailableError,
    ToolPolicyDecision,
)

if TYPE_CHECKING:
    from agentops_monitor._transport import Transport


class Span:
    """
    Context manager for a single span within a trace.

    Do not instantiate directly — use trace.span(...).
    """

    def __init__(
        self,
        transport: "Transport",
        trace_external_id: str,
        name: str,
        span_type: str = "CUSTOM",
        parent_span_id: str | None = None,
        *,
        capture_inputs: bool = True,
        capture_outputs: bool = True,
        policy_fail_mode: str = "open",
        redact_fn: Any = None,
    ) -> None:
        self._transport = transport
        self._trace_id = trace_external_id
        self._name = name
        self._type = span_type.upper()
        self._parent_span_id = parent_span_id
        self._capture_inputs = capture_inputs
        self._capture_outputs = capture_outputs
        self._policy_fail_mode = policy_fail_mode
        self._redact = redact_fn

        self.span_id: str = new_id()
        self._started_at: str = ""
        self._input: dict | None = None
        self._output: dict | None = None
        self._error: dict | None = None
        self._metadata: dict = {}
        self._pending_child_calls: list[tuple[str, dict[str, Any]]] = []
        self._finished = False

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "Span":
        self._started_at = utcnow_iso()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self._error = {
                "type": exc_type.__name__,
                "message": str(exc_val),
                "traceback": traceback.format_exc(),
            }
        self._finish(ok=exc_type is None)
        return False  # never suppress exceptions

    # ── Data setters ──────────────────────────────────────────────────────────

    def set_input(self, data: Any) -> "Span":
        if self._capture_inputs:
            self._input = self._apply_redact(safe_json(data))
        return self

    def set_output(self, data: Any) -> "Span":
        if self._capture_outputs:
            self._output = self._apply_redact(safe_json(data))
        return self

    def set_error(self, error: Exception | str | dict) -> "Span":
        if isinstance(error, Exception):
            self._error = {
                "type": type(error).__name__,
                "message": str(error),
            }
        elif isinstance(error, str):
            self._error = {"message": error}
        else:
            self._error = safe_json(error)
        return self

    def set_metadata(self, data: dict) -> "Span":
        self._metadata.update(safe_json(data))
        return self

    # ── Child calls ───────────────────────────────────────────────────────────

    def add_tool_call(
        self,
        tool_name: str,
        *,
        input: Any = None,
        output: Any = None,
        status: str = "SUCCESS",
        duration_ms: int | None = None,
        requires_approval: bool = False,
        blocked_reason: str | None = None,
    ) -> "Span":
        payload: dict[str, Any] = {
            "tool_name": tool_name,
            "status": status.upper(),
            "requires_approval": requires_approval,
        }
        if input is not None and self._capture_inputs:
            payload["input_data"] = self._apply_redact(safe_json(input))
        if output is not None and self._capture_outputs:
            payload["output_data"] = self._apply_redact(safe_json(output))
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if blocked_reason:
            payload["blocked_reason"] = blocked_reason

        self._pending_child_calls.append(("tool", payload))
        return self

    def check_tool(self, tool_name: str, *, target_url: str | None = None) -> ToolPolicyDecision:
        """Ask the backend for a decision without sending tool arguments."""
        try:
            payload = self._transport.check_tool(self._trace_id, tool_name, target_url)
            if payload is not None:
                return ToolPolicyDecision(
                    decision=PolicyDecision(payload["decision"]),
                    reason_code=str(payload["reason_code"]),
                    reason=str(payload["reason"]),
                    policy_id=payload.get("policy_id"),
                    limits=payload.get("limits") or {},
                )
        except Exception:
            pass
        return ToolPolicyDecision(
            decision=PolicyDecision.UNAVAILABLE,
            reason_code="POLICY_UNAVAILABLE",
            reason="Policy service is unavailable",
        )

    def run_tool(
        self, tool_name: str, fn: Any, *args: Any,
        target_url: str | None = None, **kwargs: Any,
    ) -> Any:
        """Check policy, execute an allowed callable, and record the outcome."""
        result = self.check_tool(tool_name, target_url=target_url)
        if result.decision == PolicyDecision.BLOCK:
            self.add_tool_call(tool_name, status="BLOCKED", blocked_reason=result.reason_code)
            raise PolicyBlockedError(result)
        if result.decision == PolicyDecision.REQUIRE_APPROVAL:
            self.add_tool_call(
                tool_name, status="PENDING_APPROVAL", requires_approval=True,
                blocked_reason=result.reason_code,
            )
            raise ApprovalRequiredError(result)
        if result.decision == PolicyDecision.UNAVAILABLE and self._policy_fail_mode == "closed":
            self.add_tool_call(tool_name, status="BLOCKED", blocked_reason=result.reason_code)
            raise PolicyUnavailableError(result)

        started = time.monotonic()
        try:
            output = fn(*args, **kwargs)
        except Exception as exc:
            self.add_tool_call(
                tool_name, output={"error_type": type(exc).__name__}, status="ERROR",
                duration_ms=int((time.monotonic() - started) * 1000),
                blocked_reason=(result.reason_code if result.decision == PolicyDecision.UNAVAILABLE else None),
            )
            raise
        self.add_tool_call(
            tool_name, output=output, status="SUCCESS",
            duration_ms=int((time.monotonic() - started) * 1000),
            blocked_reason=(result.reason_code if result.decision == PolicyDecision.UNAVAILABLE else None),
        )
        return output

    def add_model_call(
        self,
        provider: str,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost: float = 0.0,
        latency_ms: int | None = None,
        temperature: float | None = None,
        status: str = "SUCCESS",
    ) -> "Span":
        """Record model usage.

        ``estimated_cost`` is retained for source compatibility and sent as
        informational legacy data. The backend ignores it when calculating
        and persisting authoritative cost.
        """
        payload: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
            "occurred_at": utcnow_iso(),
            "status": status.upper(),
        }
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        if temperature is not None:
            payload["temperature"] = temperature

        self._pending_child_calls.append(("model", payload))
        return self

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply_redact(self, data: Any) -> Any:
        if self._redact is None:
            return data
        try:
            return self._redact(data)
        except Exception:
            return data

    def _finish(self, ok: bool) -> None:
        if self._finished:
            return
        self._finished = True

        payload: dict[str, Any] = {
            "external_span_id": self.span_id,
            "name": self._name,
            "type": self._type,
            "started_at": self._started_at,
            "ended_at": utcnow_iso(),
            "status": "SUCCESS" if ok else "ERROR",
        }
        if self._parent_span_id:
            payload["parent_span_id"] = self._parent_span_id
        if self._input is not None:
            payload["input_data"] = self._input
        if self._output is not None:
            payload["output_data"] = self._output
        if self._error is not None:
            payload["error_data"] = self._error
        if self._metadata:
            payload["metadata"] = self._metadata

        try:
            self._transport.create_span(self._trace_id, payload)
        except Exception:
            return

        for call_type, child_payload in self._pending_child_calls:
            try:
                if call_type == "tool":
                    self._transport.add_tool_call(self.span_id, child_payload)
                else:
                    self._transport.add_model_call(self.span_id, child_payload)
            except Exception:
                pass
