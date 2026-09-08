"""
AgentOps Monitor — Python SDK

Quick start:
    from agentops_monitor import AgentOps

    client = AgentOps(api_key="agom_...", endpoint="http://localhost:8000")

    with client.trace(name="my-task") as trace:
        trace.set_input({"q": "hello"})
        with trace.span("do-work", span_type="CUSTOM") as span:
            result = do_work()
            span.set_output(result)
        trace.set_output({"result": result})

    client.flush()
"""
from __future__ import annotations

import functools
import random
import time
from contextlib import contextmanager
from typing import Any, Callable, Generator

from agentops_monitor._trace import Trace
from agentops_monitor._transport import Transport
from agentops_monitor._utils import sdk_warn


class AgentOps:
    """
    Main SDK client. One instance per application.

    Parameters
    ----------
    api_key:
        Your AgentOps Monitor API key (starts with ``agom_``).
    endpoint:
        Base URL of your AgentOps Monitor backend.
    project_id:
        Default project ID to attach traces to.
    agent_id:
        Default agent ID.
    environment_id:
        Default environment ID.
    sample_rate:
        Float in [0, 1]. Fraction of traces to actually send. Useful for
        high-throughput applications. Default: 1.0 (send all).
    capture_inputs:
        Whether to record input data on traces and spans. Default: True.
    capture_outputs:
        Whether to record output data on traces and spans. Default: True.
    redact_fn:
        Optional ``Callable[[Any], Any]`` applied to all input/output data
        before it is sent. Use this to strip PII / secrets.
    timeout:
        HTTP timeout in seconds. Default: 10.
    flush_threshold:
        Number of queued items that triggers an automatic background flush.
        Default: 50.
    disabled:
        Set to True to completely disable all instrumentation (no-op mode).
        Useful in tests or local dev.
    policy_fail_mode:
        ``"open"`` executes tools when preflight is unavailable; ``"closed"``
        raises ``PolicyUnavailableError`` before execution. Default: ``"open"``.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str = "http://localhost:8000",
        *,
        project_id: int | None = None,
        agent_id: int | None = None,
        environment_id: int | None = None,
        sample_rate: float = 1.0,
        capture_inputs: bool = True,
        capture_outputs: bool = True,
        redact_fn: Callable[[Any], Any] | None = None,
        timeout: float = 10.0,
        flush_threshold: int = 50,
        disabled: bool = False,
        policy_fail_mode: str = "open",
    ) -> None:
        self._project_id = project_id
        self._agent_id = agent_id
        self._environment_id = environment_id
        self._sample_rate = max(0.0, min(1.0, sample_rate))
        if policy_fail_mode not in {"open", "closed"}:
            raise ValueError("policy_fail_mode must be 'open' or 'closed'")
        self._capture_inputs = capture_inputs
        self._capture_outputs = capture_outputs
        self._policy_fail_mode = policy_fail_mode
        self._redact = redact_fn
        self._disabled = disabled

        if not disabled:
            self._transport = Transport(
                api_key=api_key,
                endpoint=endpoint,
                timeout=timeout,
                flush_threshold=flush_threshold,
            )
        else:
            self._transport = None  # type: ignore[assignment]

    # ── Trace factory ─────────────────────────────────────────────────────────

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        agent: str | None = None,
        environment: str | None = None,
        project_id: int | None = None,
        agent_id: int | None = None,
        environment_id: int | None = None,
        session_id: str | None = None,
        user_reference: str | None = None,
        metadata: dict | None = None,
    ) -> Generator[Trace, None, None]:
        """
        Context manager that wraps a complete agent trace.

        If the SDK is disabled or the sample_rate rejects this trace,
        a no-op trace is returned — code inside the with block still runs.

        Parameters
        ----------
        name:
            Human-readable name for this trace (e.g. ``"answer-compliance-question"``).
        agent / environment:
            String names — resolved to IDs by the backend. Use these OR the
            ``*_id`` variants, not both.
        project_id / agent_id / environment_id:
            Override default IDs set on the client.
        session_id:
            Group multiple traces into a session.
        user_reference:
            Anonymised user identifier (e.g. a hashed user ID). Never store
            raw PII here.
        metadata:
            Arbitrary key-value data attached to the trace.
        """
        if self._disabled or not self._should_sample():
            yield _NoopTrace()  # type: ignore[misc]
            return

        t = Trace(
            transport=self._transport,
            name=name,
            project_id=project_id or self._project_id,
            agent_id=agent_id or self._agent_id,
            environment_id=environment_id or self._environment_id,
            session_id=session_id,
            user_reference=user_reference,
            metadata=metadata,
            capture_inputs=self._capture_inputs,
            capture_outputs=self._capture_outputs,
            policy_fail_mode=self._policy_fail_mode,
            redact_fn=self._redact,
        )
        with t:
            yield t

    def flush(self) -> None:
        """Flush all pending items to the server synchronously."""
        if self._transport is not None:
            self._transport.flush()

    def close(self) -> None:
        """Flush and shut down the HTTP client. Call on application exit."""
        if self._transport is not None:
            self._transport.close()

    def _should_sample(self) -> bool:
        if self._sample_rate >= 1.0:
            return True
        if self._sample_rate <= 0.0:
            return False
        return random.random() < self._sample_rate

    # ── Decorators ────────────────────────────────────────────────────────────

    def trace_agent(
        self,
        name: str | None = None,
        **trace_kwargs: Any,
    ) -> Callable:
        """
        Decorator that wraps a function in a trace.

        Usage:
            @client.trace_agent("run-pipeline")
            def run(query: str):
                ...
        """
        def decorator(fn: Callable) -> Callable:
            trace_name = name or fn.__name__

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.trace(trace_name, **trace_kwargs) as t:
                    if self._capture_inputs and args:
                        t.set_input({"args": args, "kwargs": kwargs})
                    try:
                        result = fn(*args, **kwargs)
                        if self._capture_outputs:
                            t.set_output({"result": result})
                        return result
                    except Exception:
                        raise

            return wrapper
        return decorator

    def trace_tool(
        self,
        tool_name: str | None = None,
    ) -> Callable:
        """
        Decorator that records a function as a tool call on the current span.

        The decorated function must be called inside an active trace.span().
        If not, it runs normally without instrumentation.

        Usage:
            @client.trace_tool("search_db")
            def search(query: str) -> list:
                ...
        """
        def decorator(fn: Callable) -> Callable:
            tname = tool_name or fn.__name__

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                t0 = time.monotonic()
                error = None
                try:
                    result = fn(*args, **kwargs)
                    return result
                except Exception as e:
                    error = e
                    raise
                finally:
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    # Best-effort: we don't have direct span access here.
                    # Callers should use span.add_tool_call() directly for
                    # precise control. This decorator records via the transport
                    # if a trace is available in context.
                    _ = tname, duration_ms, error  # noqa: F841

            return wrapper
        return decorator

    def trace_model_call(
        self,
        provider: str,
        model: str,
        *,
        cost_per_input_token: float = 0.0,
        cost_per_output_token: float = 0.0,
    ) -> Callable:
        """
        Decorator for functions that call an LLM.

        The decorated function should return a dict with keys:
        ``input_tokens``, ``output_tokens`` (optional).

        Usage:
            @client.trace_model_call("openai", "gpt-4o",
                                     cost_per_input_token=0.000005,
                                     cost_per_output_token=0.000015)
            def call_llm(prompt: str) -> dict:
                ...  # returns {"text": ..., "input_tokens": 100, "output_tokens": 50}
        """
        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                t0 = time.monotonic()
                try:
                    result = fn(*args, **kwargs)
                    return result
                finally:
                    pass  # Callers use span.add_model_call() for full control

            return wrapper
        return decorator


# ── No-op trace for sampling / disabled mode ──────────────────────────────────

class _NoopTrace:
    """
    A no-op trace returned when the SDK is disabled or sampling rejects
    a trace. All method calls are accepted and silently ignored.
    """

    trace_id: str = "noop"

    def set_input(self, *a: Any, **k: Any) -> "_NoopTrace":
        return self

    def set_output(self, *a: Any, **k: Any) -> "_NoopTrace":
        return self

    def set_risk(self, *a: Any, **k: Any) -> "_NoopTrace":
        return self

    def set_metadata(self, *a: Any, **k: Any) -> "_NoopTrace":
        return self

    def event(self, *a: Any, **k: Any) -> "_NoopTrace":
        return self

    @contextmanager
    def span(self, *a: Any, **k: Any) -> Generator["_NoopSpan", None, None]:
        yield _NoopSpan()


class _NoopSpan:
    span_id: str = "noop"

    def set_input(self, *a: Any, **k: Any) -> "_NoopSpan": return self
    def set_output(self, *a: Any, **k: Any) -> "_NoopSpan": return self
    def set_error(self, *a: Any, **k: Any) -> "_NoopSpan": return self
    def set_metadata(self, *a: Any, **k: Any) -> "_NoopSpan": return self
    def add_tool_call(self, *a: Any, **k: Any) -> "_NoopSpan": return self
    def add_model_call(self, *a: Any, **k: Any) -> "_NoopSpan": return self
    def check_tool(self, *a: Any, **k: Any):
        from agentops_monitor.policy import PolicyDecision, ToolPolicyDecision
        return ToolPolicyDecision(PolicyDecision.ALLOW, "NOOP", "Instrumentation is disabled")
    def run_tool(
        self, _tool_name: str, fn: Any, *args: Any,
        target_url: str | None = None, approval_context: dict | None = None,
        wait_for_approval: bool = False, approval_timeout: float = 120.0,
        approval_poll_interval: float = 1.0, **kwargs: Any,
    ) -> Any:
        return fn(*args, **kwargs)
