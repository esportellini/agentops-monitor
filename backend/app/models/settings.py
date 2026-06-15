from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import PrivacyRequestStatus, PrivacyRequestType


class DataRetentionPolicy(Base, TimestampMixin):
    __tablename__ = "data_retention_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # Days to retain each data type; None means keep forever
    traces_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=90)
    spans_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=90)
    audit_logs_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=365)
    cost_records_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    anonymize_user_references: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PrivacyRequest(Base, TimestampMixin):
    __tablename__ = "privacy_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    type: Mapped[PrivacyRequestType] = mapped_column(
        Enum(PrivacyRequestType, name="privacy_request_type"), nullable=False
    )
    status: Mapped[PrivacyRequestStatus] = mapped_column(
        Enum(PrivacyRequestStatus, name="privacy_request_status"),
        nullable=False,
        default=PrivacyRequestStatus.PENDING,
    )
    # Anonymized subject reference — never raw PII
    subject_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization", back_populates="privacy_requests")


class SystemSetting(Base, TimestampMixin):
    """Key-value store for operator-level configuration."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
