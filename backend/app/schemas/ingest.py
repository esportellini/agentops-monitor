"""
Ingest API schemas.

All timestamps are ISO-8601 with timezone. External IDs are opaque strings
from the SDK — we store them as-is and use them for idempotency lookups.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    ModelCallStatus,
    Severity,
    SpanStatus,
    SpanType,
    ToolCallStatus,
    TraceStatus,
)


# ── Trace ──────────────────────────────────────────────────────────────────────

class TraceStart(BaseModel):
    external_trace_id: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    # Optional IDs — validated server-side against org scope
    project_id: int | None = None
    agent_id: int | None = None
    environment_id: int | None = None
    session_id: str | None = Field(default=None, max_length=255)
    # Anonymised user reference — never raw PII
    user_reference: str | None = Field(default=None, max_length=255)
    started_at: datetime
    metadata: dict[str, Any] | None = None


class TraceFinish(BaseModel):
    status: TraceStatus
    ended_at: datetime
    risk_level: Severity = Severity.INFO
    metadata: dict[str, Any] | None = None


# ── Span ───────────────────────────────────────────────────────────────────────

class SpanCreate(BaseModel):
    external_span_id: str = Field(..., max_length=255)
    parent_span_id: str | None = Field(default=None, max_length=255)  # external span id
    name: str = Field(..., max_length=255)
    type: SpanType
    started_at: datetime
    ended_at: datetime | None = None
    status: SpanStatus = SpanStatus.RUNNING
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error_data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class SpanUpdate(BaseModel):
    ended_at: datetime | None = None
    status: SpanStatus | None = None
    output_data: dict[str, Any] | None = None
    error_data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


# ── ToolCall ───────────────────────────────────────────────────────────────────

class ToolCallCreate(BaseModel):
    tool_name: str = Field(..., max_length=255)
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    status: ToolCallStatus
    duration_ms: int | None = None
    requires_approval: bool = False
    blocked_reason: str | None = None


# ── ModelCall ──────────────────────────────────────────────────────────────────

class ModelCallCreate(BaseModel):
    provider: str = Field(..., max_length=100)
    model: str = Field(..., max_length=100)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0)
    latency_ms: int | None = None
    temperature: float | None = None
    status: ModelCallStatus


# ── TraceEvent ─────────────────────────────────────────────────────────────────

class TraceEventCreate(BaseModel):
    event_type: str = Field(..., max_length=100)
    severity: Severity = Severity.INFO
    message: str
    span_id: str | None = Field(default=None, max_length=255)  # external span id
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


# ── Batch ──────────────────────────────────────────────────────────────────────

class BatchItemType(str):
    pass


class BatchItem(BaseModel):
    type: Literal[
        "trace_start",
        "trace_finish",
        "span",
        "span_update",
        "tool_call",
        "model_call",
        "event",
    ]
    # For routing — which trace / span does this item belong to?
    external_trace_id: str | None = Field(default=None, max_length=255)
    external_span_id: str | None = Field(default=None, max_length=255)
    payload: dict[str, Any]


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(..., min_length=1, max_length=500)


class BatchItemResult(BaseModel):
    index: int
    ok: bool
    error: str | None = None


class BatchResponse(BaseModel):
    accepted: int
    failed: int
    results: list[BatchItemResult]


# ── Responses ──────────────────────────────────────────────────────────────────

class TraceOut(BaseModel):
    id: int
    external_trace_id: str | None
    name: str
    status: TraceStatus
    organization_id: int
    project_id: int
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    risk_level: Severity

    model_config = {"from_attributes": True}


class SpanOut(BaseModel):
    id: int
    trace_id: int
    external_span_id: str | None
    parent_span_id: int | None
    name: str
    type: SpanType
    status: SpanStatus
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None

    model_config = {"from_attributes": True}
