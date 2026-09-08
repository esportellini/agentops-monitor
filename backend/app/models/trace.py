from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    ModelCallStatus,
    Severity,
    SpanStatus,
    SpanType,
    ToolCallStatus,
    TraceStatus,
)

if TYPE_CHECKING:
    from app.models.project import Agent, Environment, Project
    from app.models.organization import Organization


class Trace(Base, TimestampMixin):
    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # External IDs supplied by the SDK — not globally unique, only within an org
    external_trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Anonymized reference to the end user (e.g. hashed user id), never PII
    user_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TraceStatus] = mapped_column(
        Enum(TraceStatus, name="trace_status"), nullable=False, default=TraceStatus.RUNNING, index=True
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False, default=0)
    unpriced_model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    risk_level: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity"), nullable=False, default=Severity.INFO
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    organization: Mapped[Organization] = relationship()
    project: Mapped[Project] = relationship(back_populates="traces")
    agent: Mapped[Agent | None] = relationship(back_populates="traces")
    environment: Mapped[Environment | None] = relationship(back_populates="traces")
    spans: Mapped[list[Span]] = relationship(back_populates="trace", cascade="all, delete-orphan")
    events: Mapped[list[TraceEvent]] = relationship(back_populates="trace", cascade="all, delete-orphan")
    cost_records: Mapped[list[CostRecord]] = relationship(back_populates="trace", cascade="all, delete-orphan")


class Span(Base, TimestampMixin):
    __tablename__ = "spans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trace_id: Mapped[int] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_span_id: Mapped[int | None] = mapped_column(
        ForeignKey("spans.id", ondelete="SET NULL"), nullable=True, index=True
    )

    external_span_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[SpanType] = mapped_column(
        Enum(SpanType, name="span_type"), nullable=False, index=True
    )
    status: Mapped[SpanStatus] = mapped_column(
        Enum(SpanStatus, name="span_status"), nullable=False, default=SpanStatus.RUNNING
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    trace: Mapped[Trace] = relationship(back_populates="spans")
    children: Mapped[list[Span]] = relationship(back_populates="parent")
    parent: Mapped[Span | None] = relationship(back_populates="children", remote_side="Span.id")
    tool_calls: Mapped[list[ToolCall]] = relationship(back_populates="span", cascade="all, delete-orphan")
    model_calls: Mapped[list[ModelCall]] = relationship(back_populates="span", cascade="all, delete-orphan")


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    span_id: Mapped[int] = mapped_column(
        ForeignKey("spans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tool_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ToolCallStatus] = mapped_column(
        Enum(ToolCallStatus, name="tool_call_status"), nullable=False
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    span: Mapped[Span] = relationship(back_populates="tool_calls")


class ModelCall(Base, TimestampMixin):
    __tablename__ = "model_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    span_id: Mapped[int] = mapped_column(
        ForeignKey("spans.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Legacy name: this value is the authoritative server-calculated cost.
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pricing_status: Mapped[str] = mapped_column(String(20), nullable=False)
    pricing_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_pricing.id", ondelete="SET NULL"), nullable=True, index=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[ModelCallStatus] = mapped_column(
        Enum(ModelCallStatus, name="model_call_status"), nullable=False
    )

    span: Mapped[Span] = relationship(back_populates="model_calls")


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trace_id: Mapped[int] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    span_id: Mapped[int | None] = mapped_column(
        ForeignKey("spans.id", ondelete="CASCADE"), nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity"), nullable=False, default=Severity.INFO
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    trace: Mapped[Trace] = relationship(back_populates="events")


class CostRecord(Base, TimestampMixin):
    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trace_id: Mapped[int] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_calls.id", ondelete="SET NULL"), nullable=True
    )

    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    pricing_status: Mapped[str] = mapped_column(String(20), nullable=False)
    pricing_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_pricing.id", ondelete="SET NULL"), nullable=True, index=True
    )
    input_price_per_million: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 8), nullable=True
    )
    output_price_per_million: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 8), nullable=True
    )
    pricing_effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    trace: Mapped[Trace] = relationship(back_populates="cost_records")
