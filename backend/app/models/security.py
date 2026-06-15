"""
Security models: SecurityFinding, AgentPolicy, ToolApproval.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import Severity


class SecurityFinding(Base, TimestampMixin):
    """
    A single detected security issue attached to a trace/span.
    finding_type is one of the FINDING_* constants in services/security.py.
    """
    __tablename__ = "security_findings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trace_id: Mapped[int | None] = mapped_column(
        ForeignKey("traces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    span_id: Mapped[int | None] = mapped_column(
        ForeignKey("spans.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    finding_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Raw evidence: matched text, redacted content, rule that fired, etc.
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Action taken: "detect", "redact", "alert", "block"
    action_taken: Mapped[str] = mapped_column(String(50), nullable=False, default="detect")
    # Optional: redacted version of the field that triggered this finding
    redacted_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentPolicy(Base, TimestampMixin):
    """
    Security and operational policy scoped to a specific agent.
    Controls tool usage, token/cost limits, domain restrictions,
    data capture settings, and redaction behaviour.
    """
    __tablename__ = "agent_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Tool controls ────────────────────────────────────────────────────────
    # [] means unrestricted; explicit list enables allowlist mode
    allowed_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    blocked_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    tools_requiring_approval: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Resource limits ───────────────────────────────────────────────────────
    max_tokens_per_trace: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_cost_per_trace_usd: Mapped[float | None] = mapped_column(nullable=True)

    # ── Domain controls ───────────────────────────────────────────────────────
    allowed_domains: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    blocked_domains: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Data capture ──────────────────────────────────────────────────────────
    capture_inputs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    capture_outputs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Detection behaviour: "detect" | "redact" | "alert" | "block" ────────
    pii_action: Mapped[str] = mapped_column(String(20), nullable=False, default="alert")
    secret_action: Mapped[str] = mapped_column(String(20), nullable=False, default="block")
    injection_action: Mapped[str] = mapped_column(String(20), nullable=False, default="alert")

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ToolApproval(Base, TimestampMixin):
    """
    Pending or resolved approval request for a tool call that requires
    human sign-off per agent policy.
    """
    __tablename__ = "tool_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trace_id: Mapped[int | None] = mapped_column(
        ForeignKey("traces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    span_id: Mapped[int | None] = mapped_column(
        ForeignKey("spans.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # "pending" | "approved" | "rejected"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
