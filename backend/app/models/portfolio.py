from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..crypto.fields import EncryptedDecimal, EncryptedStr
from ..db import Base
from .auth import utcnow

ASSET_CLASSES = {"equity", "mutual_fund", "etf", "gold", "crypto", "bond",
                 "cash", "fd", "epf", "ppf", "real_estate", "other"}
TXN_TYPES = {"buy", "sell", "dividend", "split", "bonus", "fee", "deposit", "withdrawal"}


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32), default="broker")  # broker/bank/mf/retirement/cash/other
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    country: Mapped[str] = mapped_column(String(2), default="IN")
    account_number: Mapped[str | None] = mapped_column(EncryptedStr, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transactions: Mapped[list[Transaction]] = relationship(back_populates="account")


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Provider-ready symbol: RELIANCE.NS, TCS.BO, AAPL, VTI. Mutual funds use MF:<amfi_code>.
    symbol: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")  # NSE/BSE/NASDAQ/NYSE/AMFI/OTHER
    isin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(16), default="equity")
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    country: Mapped[str] = mapped_column(String(2), default="IN")

    transactions: Mapped[list[Transaction]] = relationship(back_populates="instrument")


class Transaction(Base):
    """Ledger row. Quantities/prices/amounts are encrypted at rest.

    Semantics by type:
      buy/sell   quantity + price (+fees)
      dividend   amount (cash received)
      split      quantity = multiplier factor (e.g. 5 for a 1:5 split)
      bonus      quantity = shares received (zero-cost FIFO lot)
      fee        amount
      deposit/withdrawal  amount (cash accounts)
    """

    __tablename__ = "transactions"
    __table_args__ = (Index("ix_txn_instrument_date", "instrument_id", "trade_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=True)
    type: Mapped[str] = mapped_column(String(16))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[Decimal | None] = mapped_column(EncryptedDecimal, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(EncryptedDecimal, nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(EncryptedDecimal, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(EncryptedDecimal, nullable=True)
    notes: Mapped[str | None] = mapped_column(EncryptedStr, nullable=True)
    import_batch: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account: Mapped[Account] = relationship(back_populates="transactions")
    instrument: Mapped[Instrument | None] = relationship(back_populates="transactions")


class ManualAsset(Base):
    """Assets without a market feed: FDs, EPF/PPF, real estate, physical gold."""

    __tablename__ = "manual_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    asset_class: Mapped[str] = mapped_column(String(16), default="fd")
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    invested: Mapped[Decimal | None] = mapped_column(EncryptedDecimal, nullable=True)
    current_value: Mapped[Decimal] = mapped_column(EncryptedDecimal)
    as_of: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(EncryptedStr, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
