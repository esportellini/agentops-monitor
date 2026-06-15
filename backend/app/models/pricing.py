from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ModelPricing(Base, TimestampMixin):
    """
    Pricing table for LLM model calls.

    Prices are in USD per million tokens. Multiple rows can exist for the
    same provider+model to represent price changes over time; the system
    uses the row whose effective_from <= call_time < effective_to (or
    effective_to IS NULL for the current price).

    All calculations must go through the pricing service — never hardcode
    prices in application code.
    """

    __tablename__ = "model_pricing"
    __table_args__ = (
        Index("ix_model_pricing_lookup", "provider", "model", "effective_from"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Price in USD per 1,000,000 tokens
    input_price_per_million: Mapped[float] = mapped_column(Numeric(14, 8), nullable=False)
    output_price_per_million: Mapped[float] = mapped_column(Numeric(14, 8), nullable=False)

    # Validity window
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soft-disable without deleting historical data
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
