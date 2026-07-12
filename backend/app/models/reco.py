from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..crypto.fields import EncryptedJSON, EncryptedStr
from ..db import Base
from .auth import utcnow
from .portfolio import Instrument

SEVERITIES = ("info", "warning", "action")
CATEGORIES = ("portfolio_health", "signal", "tax")


class Recommendation(Base):
    """One finding from an engine run. Title/rationale/data reveal position
    details, so they are encrypted at rest."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(64))       # e.g. "concentration.single_stock"
    category: Mapped[str] = mapped_column(String(24))   # portfolio_health | signal | tax
    severity: Mapped[str] = mapped_column(String(12))   # info | warning | action
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(EncryptedStr)
    rationale: Mapped[str] = mapped_column(EncryptedStr)
    data: Mapped[dict | None] = mapped_column(EncryptedJSON, nullable=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    instrument: Mapped[Instrument | None] = relationship()
