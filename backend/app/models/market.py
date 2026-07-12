from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class PriceBar(Base):
    """EOD OHLC cache. Public market data — intentionally not encrypted."""

    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("instrument_id", "bar_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), index=True)
    bar_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("pair", "rate_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pair: Mapped[str] = mapped_column(String(8), index=True)  # "USDINR"
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    rate: Mapped[float] = mapped_column(Float)
