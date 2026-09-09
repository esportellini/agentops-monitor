from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import AlertIncidentStatus, AlertRuleStatus, Severity


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    condition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity"), nullable=False, default=Severity.MEDIUM
    )
    status: Mapped[AlertRuleStatus] = mapped_column(
        Enum(AlertRuleStatus, name="alert_rule_status"), nullable=False, default=AlertRuleStatus.ACTIVE
    )
    notification_channels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    incidents: Mapped[list[AlertIncident]] = relationship(back_populates="rule")


class AlertIncident(Base, TimestampMixin):
    __tablename__ = "alert_incidents"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_alert_incident_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    trace_id: Mapped[int | None] = mapped_column(
        ForeignKey("traces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity"), nullable=False, default=Severity.MEDIUM, index=True
    )
    status: Mapped[AlertIncidentStatus] = mapped_column(
        Enum(AlertIncidentStatus, name="alert_incident_status"),
        nullable=False,
        default=AlertIncidentStatus.OPEN,
    )
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    rule: Mapped[AlertRule] = relationship(back_populates="incidents")
