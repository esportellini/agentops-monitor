"""
HTTP transport for the AgentOps Monitor SDK.

Design principles:
- Never raise to the caller. All network failures are caught and logged.
- Retry with exponential backoff + jitter on 429 / 5xx.
- Batch endpoint is used for efficiency; falls back to individual calls on error.
- API key is never written to logs.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from typing import Any

import httpx

from agentops_monitor._utils import mask_key, sdk_warn

log = logging.getLogger("agentops_monitor.transport")

_DEFAULT_TIMEOUT = 10.0          # seconds per request
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.4              # seconds
_BATCH_MAX = 200                 # items per batch flush
_QUEUE_MAX = 2_000               # drop oldest when queue overflows


class Transport:
    """
    Thread-safe HTTP client.

    Maintains an in-memory queue of pending batch items.
    Items are flushed:
    - automatically when the queue reaches the flush threshold, or
    - on explicit flush() / close() calls.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
        flush_threshold: int = 50,
    ) -> None:
        self._api_key = api_key
        self._base = endpoint.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._flush_threshold = flush_threshold

        self._queue: deque[dict[str, Any]] = deque(maxlen=_QUEUE_MAX)
        self._lock = threading.Lock()

        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "agentops-monitor-python/0.1.0",
            },
            timeout=timeout,
        )

    # ── Queue management ──────────────────────────────────────────────────────

    def enqueue(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._queue.append(item)
            should_flush = len(self._queue) >= self._flush_threshold

        if should_flush:
            self._flush_async()

    def flush(self) -> None:
        """Synchronously flush all pending items."""
        with self._lock:
            items = list(self._queue)
            self._queue.clear()

        if items:
            self._send_batch(items)

    def _flush_async(self) -> None:
        """Flush in a background thread so callers aren't blocked."""
        t = threading.Thread(target=self.flush, daemon=True, name="agentops-flush")
        t.start()

    def close(self) -> None:
        """Flush remaining items and close the HTTP client."""
        self.flush()
        try:
            self._client.close()
        except Exception:
            pass

    # ── HTTP primitives ───────────────────────────────────────────────────────

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """
        POST to a single endpoint. Returns parsed JSON or None on failure.
        Retries on transient errors.
        """
        url = f"{self._base}{path}"
        for attempt in range(self._max_retries):
            try:
                resp = self._client.post(url, json=payload)
                if resp.status_code in (429, 502, 503, 504):
                    self._sleep_backoff(attempt)
                    continue
                if resp.is_success:
                    return resp.json()
                # 4xx that are not retryable
                sdk_warn(
                    "agentops: HTTP %d on %s — %s",
                    resp.status_code,
                    path,
                    resp.text[:200],
                )
                return None
            except httpx.TimeoutException:
                sdk_warn("agentops: timeout on %s (attempt %d)", path, attempt + 1)
                self._sleep_backoff(attempt)
            except httpx.NetworkError as e:
                sdk_warn("agentops: network error on %s: %s", path, e)
                self._sleep_backoff(attempt)
            except Exception as e:
                sdk_warn("agentops: unexpected error on %s: %s", path, e)
                return None
        return None

    def _send_batch(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        chunks = [items[i : i + _BATCH_MAX] for i in range(0, len(items), _BATCH_MAX)]
        for chunk in chunks:
            result = self.post("/ingest/batch", {"items": chunk})
            if result and result.get("failed", 0) > 0:
                sdk_warn(
                    "agentops: batch had %d failures out of %d",
                    result["failed"],
                    result["accepted"] + result["failed"],
                )

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        delay = _BACKOFF_BASE * (2**attempt) + random.uniform(0, 0.1)
        time.sleep(min(delay, 8.0))

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def start_trace(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.post("/ingest/traces/start", payload)

    def finish_trace(self, external_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.post(f"/ingest/traces/{external_id}/finish", payload)

    def create_span(self, external_trace_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.post(f"/ingest/traces/{external_trace_id}/spans", payload)

    def update_span(self, external_span_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.post(f"/ingest/spans/{external_span_id}", payload)

    def add_tool_call(self, external_span_id: str, payload: dict[str, Any]) -> None:
        self.post(f"/ingest/spans/{external_span_id}/tool-calls", payload)

    def add_model_call(self, external_span_id: str, payload: dict[str, Any]) -> None:
        self.post(f"/ingest/spans/{external_span_id}/model-calls", payload)

    def add_event(self, external_trace_id: str, payload: dict[str, Any]) -> None:
        self.post(f"/ingest/traces/{external_trace_id}/events", payload)

    def check_tool(
        self, external_trace_id: str, tool_name: str, target_url: str | None = None
    ) -> dict[str, Any] | None:
        payload = {"external_trace_id": external_trace_id, "tool_name": tool_name}
        if target_url is not None:
            payload["target_url"] = target_url
        return self.post("/ingest/policy/check-tool", payload)
