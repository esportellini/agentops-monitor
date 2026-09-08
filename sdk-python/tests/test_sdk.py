"""
SDK tests.

Uses respx to mock HTTP — no real server needed.
Tests cover:
  - context manager happy path
  - exception inside span → ERROR status
  - exception inside trace → ERROR + event
  - batch flushing
  - retry on 5xx
  - API failure never raises to caller
  - redact_fn strips sensitive data
  - sample_rate=0 skips all traces
  - capture_inputs=False omits data
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import respx
import httpx

from agentops_monitor import (
    AgentOps, Trace, Span, ApprovalRequiredError, PolicyBlockedError,
    PolicyDecision, PolicyUnavailableError,
)
from agentops_monitor._transport import Transport
from agentops_monitor._utils import safe_json, mask_key


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_client(**kwargs) -> AgentOps:
    return AgentOps(
        api_key="agom_testkey00000000",
        endpoint="http://fake.agentops.local",
        **kwargs,
    )


def ok_response(data: dict | None = None) -> httpx.Response:
    import json
    return httpx.Response(200, content=json.dumps(data or {"id": 1}).encode())


def policy_response(decision: str, code: str) -> httpx.Response:
    return ok_response({
        "decision": decision, "reason_code": code, "reason": code,
        "policy_id": 7, "limits": {},
    })


@respx.mock
def test_check_tool_and_run_tool_allow():
    respx.post(url__regex=r".*/traces/start").mock(return_value=ok_response())
    check = respx.post("http://fake.agentops.local/ingest/policy/check-tool").mock(
        return_value=policy_response("ALLOW", "POLICY_ALLOWED")
    )
    respx.post(url__regex=r".*/spans$").mock(return_value=ok_response())
    tool = respx.post(url__regex=r".*/tool-calls$").mock(return_value=ok_response())
    respx.post(url__regex=r".*/finish$").mock(return_value=ok_response())
    with make_client().trace("policy") as trace:
        with trace.span("tool") as span:
            decision = span.check_tool("search", target_url="https://example.com")
            assert decision.decision == PolicyDecision.ALLOW
            assert span.run_tool("search", lambda value: value + 1, 2) == 3
    assert check.call_count == 2
    assert tool.calls.last.request.content.find(b'"status":"SUCCESS"') >= 0


@pytest.mark.parametrize(
    ("decision", "error", "status"),
    [
        ("BLOCK", PolicyBlockedError, "BLOCKED"),
        ("REQUIRE_APPROVAL", ApprovalRequiredError, "PENDING_APPROVAL"),
    ],
)
@respx.mock
def test_run_tool_enforces_negative_decisions(decision, error, status):
    respx.post(url__regex=r".*/traces/start").mock(return_value=ok_response())
    respx.post("http://fake.agentops.local/ingest/policy/check-tool").mock(
        return_value=policy_response(decision, "DENIED")
    )
    respx.post(url__regex=r".*/spans$").mock(return_value=ok_response())
    tool = respx.post(url__regex=r".*/tool-calls$").mock(return_value=ok_response())
    respx.post(url__regex=r".*/events$").mock(return_value=ok_response())
    respx.post(url__regex=r".*/finish$").mock(return_value=ok_response())
    called = False
    with pytest.raises(error):
        with make_client().trace("policy") as trace:
            with trace.span("tool") as span:
                def forbidden():
                    nonlocal called
                    called = True
                span.run_tool("shell", forbidden)
    assert called is False
    assert f'"status":"{status}"'.encode() in tool.calls.last.request.content


@respx.mock
def test_policy_unavailable_fail_modes_are_explicit():
    respx.post(url__regex=r".*/traces/start").mock(return_value=ok_response())
    respx.post("http://fake.agentops.local/ingest/policy/check-tool").mock(
        return_value=httpx.Response(503)
    )
    respx.post(url__regex=r".*/spans$").mock(return_value=ok_response())
    respx.post(url__regex=r".*/tool-calls$").mock(return_value=ok_response())
    respx.post(url__regex=r".*/events$").mock(return_value=ok_response())
    respx.post(url__regex=r".*/finish$").mock(return_value=ok_response())
    with make_client(policy_fail_mode="open").trace("open") as trace:
        with trace.span("tool") as span:
            assert span.run_tool("search", lambda: 42) == 42
    with pytest.raises(PolicyUnavailableError):
        with make_client(policy_fail_mode="closed").trace("closed") as trace:
            with trace.span("tool") as span:
                span.run_tool("search", lambda: 42)


# ── Utility tests ─────────────────────────────────────────────────────────────

def test_safe_json_primitives():
    assert safe_json(None) is None
    assert safe_json(42) == 42
    assert safe_json("hello") == "hello"
    assert safe_json([1, 2, 3]) == [1, 2, 3]
    assert safe_json({"a": 1}) == {"a": 1}


def test_safe_json_non_serialisable():
    class Obj:
        def __repr__(self): return "<Obj>"
    result = safe_json(Obj())
    assert isinstance(result, str)
    assert "Obj" in result


def test_mask_key():
    key = "agom_abcdefgh1234"
    masked = mask_key(key)
    assert "abcdefgh" in masked
    assert "1234" in masked
    assert key not in masked  # middle is hidden


# ── Context manager tests ─────────────────────────────────────────────────────

@respx.mock
def test_trace_happy_path():
    respx.post("http://fake.agentops.local/ingest/traces/start").mock(
        return_value=ok_response({"id": 1, "status": "RUNNING"})
    )
    respx.post(url__regex=r".*/finish").mock(return_value=ok_response())

    client = make_client()
    with client.trace("test-trace") as trace:
        assert trace.trace_id != "noop"
        assert isinstance(trace, Trace)


@respx.mock
def test_span_happy_path():
    respx.post(url__regex=r".*/traces/start").mock(return_value=ok_response({"id": 1}))
    respx.post(url__regex=r".*/spans").mock(return_value=ok_response({"id": 10}))
    respx.post(url__regex=r".*/finish").mock(return_value=ok_response())

    client = make_client()
    with client.trace("trace-with-span") as trace:
        with trace.span("my-span", span_type="LLM") as span:
            assert isinstance(span, Span)
            span.set_input({"q": "hello"})
            span.set_output({"answer": "world"})


def test_span_is_created_before_its_child_calls():
    """Child records must never reference a span that is not persisted yet."""
    client = make_client()
    order: list[str] = []

    with (
        patch.object(Transport, "start_trace", return_value={"id": 1}),
        patch.object(Transport, "finish_trace"),
        patch.object(Transport, "create_span", side_effect=lambda *_: order.append("span")),
        patch.object(Transport, "add_tool_call", side_effect=lambda *_: order.append("tool")),
        patch.object(Transport, "add_model_call", side_effect=lambda *_: order.append("model")),
    ):
        with client.trace("ordered-trace") as trace:
            with trace.span("ordered-span") as span:
                span.add_tool_call("search")
                span.add_model_call("openai", "gpt-test")

    assert order == ["span", "tool", "model"]


def test_model_call_automatically_includes_utc_occurred_at():
    client = make_client()
    captured: dict[str, Any] = {}

    with (
        patch.object(Transport, "start_trace", return_value={"id": 1}),
        patch.object(Transport, "finish_trace"),
        patch.object(Transport, "create_span"),
        patch.object(
            Transport,
            "add_model_call",
            side_effect=lambda _span_id, payload: captured.update(payload),
        ),
    ):
        with client.trace("timestamped-trace") as trace:
            with trace.span("timestamped-span") as span:
                span.add_model_call("openai", "gpt-4o", input_tokens=5)

    occurred_at = datetime.fromisoformat(captured["occurred_at"])
    assert occurred_at.tzinfo is not None
    assert occurred_at.utcoffset() == timezone.utc.utcoffset(occurred_at)


@respx.mock
def test_exception_inside_span_sets_error_status():
    respx.post(url__regex=r".*").mock(return_value=ok_response())

    client = make_client()
    captured_span_payload: dict = {}

    original_create = Transport.create_span

    def capturing_create(self, trace_id, payload):
        captured_span_payload.update(payload)
        return original_create(self, trace_id, payload)

    with patch.object(Transport, "create_span", capturing_create):
        with client.trace("trace-with-error") as trace:
            try:
                with trace.span("failing-span") as span:
                    raise ValueError("something went wrong")
            except ValueError:
                pass  # exception propagates out of span but not trace

    assert captured_span_payload.get("status") == "ERROR"
    assert "error_data" in captured_span_payload
    assert "ValueError" in captured_span_payload["error_data"]["type"]


@respx.mock
def test_exception_inside_trace_sets_error_status():
    respx.post(url__regex=r".*").mock(return_value=ok_response())

    client = make_client()
    captured_finish: dict = {}

    original_finish = Transport.finish_trace

    def capturing_finish(self, ext_id, payload):
        captured_finish.update(payload)
        return original_finish(self, ext_id, payload)

    with patch.object(Transport, "finish_trace", capturing_finish):
        try:
            with client.trace("error-trace"):
                raise RuntimeError("trace-level failure")
        except RuntimeError:
            pass

    assert captured_finish.get("status") == "ERROR"


# ── Batch tests ───────────────────────────────────────────────────────────────

def test_batch_enqueue_and_flush():
    calls: list[dict] = []

    client = make_client(flush_threshold=100)  # won't auto-flush

    def fake_post(self, path, payload):
        calls.append({"path": path, "payload": payload})
        return {"accepted": len(payload.get("items", [])), "failed": 0, "results": []}

    with patch.object(Transport, "post", fake_post):
        # Manually enqueue items
        for i in range(5):
            client._transport.enqueue({
                "type": "event",
                "external_trace_id": f"trace-{i}",
                "payload": {"event_type": "test", "severity": "INFO", "message": f"msg {i}"},
            })
        client.flush()

    # Should have been sent in one batch call
    assert len(calls) == 1
    assert calls[0]["path"] == "/ingest/batch"
    assert len(calls[0]["payload"]["items"]) == 5


def test_batch_partial_failure_logged(caplog):
    import logging

    client = make_client()

    def fake_post(self, path, payload):
        return {"accepted": 3, "failed": 2, "results": []}

    with patch.object(Transport, "post", fake_post):
        with patch.object(Transport, "_send_batch") as mock_batch:
            mock_batch.return_value = None
            # directly test warning path
            client._transport._send_batch = lambda items: fake_post(None, "/ingest/batch", {"items": items})

        with caplog.at_level(logging.WARNING, logger="agentops_monitor.transport"):
            client._transport._send_batch([{"type": "event"} for _ in range(5)])


# ── Retry tests ───────────────────────────────────────────────────────────────

@respx.mock
def test_retry_on_503():
    attempts = []

    def side_effect(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503, content=b'{"detail":"unavailable"}')
        return ok_response({"id": 1})

    respx.post("http://fake.agentops.local/ingest/traces/start").mock(side_effect=side_effect)
    respx.post(url__regex=r".*/finish").mock(return_value=ok_response())

    client = make_client()
    # Patch sleep to avoid slow tests
    with patch("agentops_monitor._transport.time.sleep"):
        with client.trace("retry-trace"):
            pass

    assert len(attempts) == 3


# ── API failure isolation tests ───────────────────────────────────────────────

@respx.mock
def test_api_down_does_not_raise():
    """If the backend is completely unreachable, the SDK must not crash the app."""
    respx.post(url__regex=r".*").mock(side_effect=httpx.ConnectError("refused"))

    client = make_client()
    with patch("agentops_monitor._transport.time.sleep"):
        result = None
        with client.trace("offline-trace") as trace:
            trace.set_input({"q": "test"})
            with trace.span("work") as span:
                span.set_output({"done": True})
            result = "completed"

    # App logic ran to completion despite API being down
    assert result == "completed"


@respx.mock
def test_timeout_does_not_raise():
    respx.post(url__regex=r".*").mock(side_effect=httpx.TimeoutException("timeout"))

    client = make_client(timeout=0.001)
    with patch("agentops_monitor._transport.time.sleep"):
        with client.trace("timeout-trace") as trace:
            trace.set_input({"x": 1})


# ── Redaction tests ───────────────────────────────────────────────────────────

@respx.mock
def test_redact_fn_applied_to_inputs():
    respx.post(url__regex=r".*").mock(return_value=ok_response())

    captured: list[dict] = []

    def redact(data):
        if isinstance(data, dict):
            return {k: "***" if k in ("password", "secret") else v for k, v in data.items()}
        return data

    client = make_client(redact_fn=redact)
    original_create = Transport.create_span

    def spy_create(self, trace_id, payload):
        captured.append(payload)
        return original_create(self, trace_id, payload)

    with patch.object(Transport, "create_span", spy_create):
        with client.trace("redact-trace") as trace:
            with trace.span("login") as span:
                span.set_input({"username": "alice", "password": "hunter2"})

    assert captured
    inp = captured[0].get("input_data", {})
    assert inp.get("password") == "***"
    assert inp.get("username") == "alice"


@respx.mock
def test_redact_fn_exception_is_silent():
    """If the redact function itself raises, the SDK should still work."""
    respx.post(url__regex=r".*").mock(return_value=ok_response())

    def bad_redact(data):
        raise RuntimeError("redact broken")

    client = make_client(redact_fn=bad_redact)
    # Should not raise
    with client.trace("redact-error-trace") as trace:
        with trace.span("work") as span:
            span.set_input({"safe": "data"})


# ── Sample rate tests ─────────────────────────────────────────────────────────

def test_sample_rate_zero_returns_noop():
    from agentops_monitor.client import _NoopTrace

    client = make_client(sample_rate=0.0)
    with client.trace("should-be-noop") as trace:
        assert isinstance(trace, _NoopTrace)


def test_sample_rate_one_returns_real_trace():
    calls: list = []

    def fake_start(self, payload):
        calls.append(payload)
        return {"id": 1}

    def fake_finish(self, ext_id, payload):
        return {"id": 1}

    client = make_client(sample_rate=1.0)
    with patch.object(Transport, "start_trace", fake_start), \
         patch.object(Transport, "finish_trace", fake_finish):
        with client.trace("should-be-real") as trace:
            assert trace.trace_id != "noop"

    assert len(calls) == 1


def test_sample_rate_statistical():
    """With sample_rate=0.5 roughly half the traces should be no-ops."""
    from agentops_monitor.client import _NoopTrace

    noop_count = 0
    total = 200
    client = make_client(sample_rate=0.5)

    with patch.object(Transport, "start_trace", return_value={"id": 1}), \
         patch.object(Transport, "finish_trace", return_value={"id": 1}):
        for _ in range(total):
            with client.trace("sampled") as trace:
                if isinstance(trace, _NoopTrace):
                    noop_count += 1

    # Should be roughly 50% — allow generous range for statistical variance
    assert 60 < noop_count < 140


# ── Capture IO disabled ───────────────────────────────────────────────────────

@respx.mock
def test_capture_inputs_false_omits_data():
    respx.post(url__regex=r".*").mock(return_value=ok_response())

    captured: list[dict] = []
    original = Transport.create_span

    def spy(self, trace_id, payload):
        captured.append(payload)
        return original(self, trace_id, payload)

    client = make_client(capture_inputs=False, capture_outputs=False)
    with patch.object(Transport, "create_span", spy):
        with client.trace("no-io-trace") as trace:
            with trace.span("work") as span:
                span.set_input({"sensitive": "data"})
                span.set_output({"result": "value"})

    assert captured
    assert "input_data" not in captured[0]
    assert "output_data" not in captured[0]


@respx.mock
def test_capture_inputs_and_outputs_are_independent():
    respx.post(url__regex=r".*").mock(return_value=ok_response())
    captured: list[dict] = []
    original = Transport.create_span

    def spy(self, trace_id, payload):
        captured.append(payload)
        return original(self, trace_id, payload)

    client = make_client(capture_inputs=False, capture_outputs=True)
    with patch.object(Transport, "create_span", spy):
        with client.trace("output-only") as trace:
            with trace.span("work") as span:
                span.set_input({"sensitive": "data"})
                span.set_output({"result": "value"})

    assert "input_data" not in captured[0]
    assert captured[0]["output_data"] == {"result": "value"}


# ── Nested spans ──────────────────────────────────────────────────────────────

@respx.mock
def test_nested_spans_have_parent_id():
    respx.post(url__regex=r".*").mock(return_value=ok_response())

    spans: list[dict] = []
    original = Transport.create_span

    def spy(self, trace_id, payload):
        spans.append(payload)
        return original(self, trace_id, payload)

    client = make_client()
    with patch.object(Transport, "create_span", spy):
        with client.trace("nested-trace") as trace:
            with trace.span("parent-span") as parent:
                with trace.span("child-span") as child:
                    pass

    parent_span = next(s for s in spans if s["name"] == "parent-span")
    child_span = next(s for s in spans if s["name"] == "child-span")

    assert child_span.get("parent_span_id") == parent_span["external_span_id"]
    assert "parent_span_id" not in parent_span or parent_span.get("parent_span_id") is None


# ── Disabled mode ─────────────────────────────────────────────────────────────

def test_disabled_client_is_noop():
    from agentops_monitor.client import _NoopTrace

    client = AgentOps(api_key="agom_test", endpoint="http://nowhere", disabled=True)
    # No HTTP calls should be made — client has no transport
    result = None
    with client.trace("disabled") as trace:
        assert isinstance(trace, _NoopTrace)
        result = "ran"

    assert result == "ran"
    client.flush()  # should not raise
    client.close()  # should not raise
