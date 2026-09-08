"""
Trace: top-level unit of agent execution.

Usage:
    with client.trace(agent="my-agent", name="answer-question") as trace:
        trace.set_input({"q": "..."})
        with trace.span("llm-call", span_type="llm") as span:
            span.add_model_call("openai", "gpt-4o", input_tokens=200, ...)
        trace.set_output({"answer": "..."})
"""
from __future__ import annotations

import traceback
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Generator

from agentops_monitor._span import Span
from agentops_monitor._utils import new_id, safe_json, utcnow_iso

if TYPE_CHECKING:
    from agentops_monitor._transport import Transport


class Trace:
    """
    Context manager for a complete agent trace.

    Do not instantiate directly — use AgentOps.trace(...).
    """

    def __init__(
        self,
        transport: "Transport",
        *,
        name: str,
        project_id: int | None,
        agent_id: int | None,
        environment_id: int | None,
        session_id: str | None,
        user_reference: str | None,
        metadata: dict | None,
        capture_inputs: bool,
        capture_outputs: bool,
        policy_fail_mode: str,
        redact_fn: Any,
    ) -> None:
        self._transport = transport
        self._name = name
        self._project_id = project_id
        self._agent_id = agent_id
        self._environment_id = environment_id
        self._session_id = session_id
        self._user_reference = user_reference
        self._meta = metadata or {}
        self._capture_inputs = capture_inputs
        self._capture_outputs = capture_outputs
        self._policy_fail_mode = policy_fail_mode
        self._redact = redact_fn

        self.trace_id: str = new_id()
        self._started_at: str = ""
        self._input: dict | None = None
        self._output: dict | None = None
        self._risk_level: str = "INFO"
        self._finished = False

        # Stack for nested spans — each span knows its own parent
        self._span_stack: list[str] = []

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "Trace":
        self._started_at = utcnow_iso()
        payload: dict[str, Any] = {
            "external_trace_id": self.trace_id,
            "name": self._name,
            "started_at": self._started_at,
        }
        if self._project_id:
            payload["project_id"] = self._project_id
        if self._agent_id:
            payload["agent_id"] = self._agent_id
        if self._environment_id:
            payload["environment_id"] = self._environment_id
        if self._session_id:
            payload["session_id"] = self._session_id
        if self._user_reference:
            payload["user_reference"] = self._user_reference
        if self._meta:
            payload["metadata"] = self._meta

        try:
            self._transport.start_trace(payload)
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self._risk_level = "HIGH"
            try:
                self._transport.add_event(
                    self.trace_id,
                    {
                        "event_type": "exception",
                        "severity": "HIGH",
                        "message": f"{exc_type.__name__}: {exc_val}",
                        "metadata": {"traceback": traceback.format_exc()},
                        "created_at": utcnow_iso(),
                    },
                )
            except Exception:
                pass
        self._finish(ok=exc_type is None)
        return False

    # ── Data setters ──────────────────────────────────────────────────────────

    def set_input(self, data: Any) -> "Trace":
        if self._capture_inputs:
            self._input = self._apply_redact(safe_json(data))
        return self

    def set_output(self, data: Any) -> "Trace":
        if self._capture_outputs:
            self._output = self._apply_redact(safe_json(data))
        return self

    def set_risk(self, level: str) -> "Trace":
        """Set risk level: INFO, LOW, MEDIUM, HIGH, CRITICAL."""
        self._risk_level = level.upper()
        return self

    def set_metadata(self, data: dict) -> "Trace":
        self._meta.update(safe_json(data))
        return self

    # ── Span factory ──────────────────────────────────────────────────────────

    @contextmanager
    def span(
        self,
        name: str,
        span_type: str = "CUSTOM",
    ) -> Generator[Span, None, None]:
        """
        Create a child span. Spans can be nested — the parent is tracked
        automatically via the span stack.
        """
        parent_id = self._span_stack[-1] if self._span_stack else None
        s = Span(
            transport=self._transport,
            trace_external_id=self.trace_id,
            name=name,
            span_type=span_type,
            parent_span_id=parent_id,
            capture_inputs=self._capture_inputs,
            capture_outputs=self._capture_outputs,
            policy_fail_mode=self._policy_fail_mode,
            redact_fn=self._redact,
        )
        self._span_stack.append(s.span_id)
        try:
            with s:
                yield s
        finally:
            if self._span_stack and self._span_stack[-1] == s.span_id:
                self._span_stack.pop()

    # ── Events ────────────────────────────────────────────────────────────────

    def event(
        self,
        event_type: str,
        message: str,
        *,
        severity: str = "INFO",
        metadata: dict | None = None,
    ) -> "Trace":
        payload: dict[str, Any] = {
            "event_type": event_type,
            "severity": severity.upper(),
            "message": message,
            "created_at": utcnow_iso(),
        }
        if metadata:
            payload["metadata"] = safe_json(metadata)
        try:
            self._transport.add_event(self.trace_id, payload)
        except Exception:
            pass
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
            "status": "SUCCESS" if ok else "ERROR",
            "ended_at": utcnow_iso(),
            "risk_level": self._risk_level,
        }
        if self._meta:
            payload["metadata"] = self._meta

        try:
            self._transport.finish_trace(self.trace_id, payload)
        except Exception:
            pass
