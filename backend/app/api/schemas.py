from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.portfolio import ASSET_CLASSES, TXN_TYPES


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: str = "broker"
    currency: str = "INR"
    country: str = "IN"
    account_number: str | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    kind: str
    currency: str
    country: str
    account_number: str | None
    created_at: datetime


class InstrumentIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    name: str
    exchange: str = "NSE"
    isin: str | None = None
    asset_class: str = "equity"
    sector: str | None = None
    currency: str = "INR"
    country: str = "IN"

    @field_validator("asset_class")
    @classmethod
    def _valid_class(cls, v: str) -> str:
        if v not in ASSET_CLASSES:
            raise ValueError(f"asset_class must be one of {sorted(ASSET_CLASSES)}")
        return v


class InstrumentOut(InstrumentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TransactionIn(BaseModel):
    account_id: int
    instrument_id: int | None = None
    type: str
    trade_date: date
    quantity: Decimal | None = None
    price: Decimal | None = None
    fees: Decimal | None = None
    amount: Decimal | None = None
    notes: str | None = None

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in TXN_TYPES:
            raise ValueError(f"type must be one of {sorted(TXN_TYPES)}")
        return v


class TransactionOut(TransactionIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    import_batch: str | None
    created_at: datetime


class ManualAssetIn(BaseModel):
    name: str
    asset_class: str = "fd"
    currency: str = "INR"
    invested: Decimal | None = None
    current_value: Decimal
    as_of: date
    maturity_date: date | None = None
    notes: str | None = None


class ManualAssetOut(ManualAssetIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class HoldingOut(BaseModel):
    instrument: InstrumentOut
    quantity: float
    avg_cost: float
    invested: float
    current_price: float | None
    price_date: date | None
    current_value: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    realized_pnl: float
    dividends: float


class PortfolioSummary(BaseModel):
    base_currency: str
    net_worth: float | None
    equity_value: float | None
    manual_assets_value: float | None
    invested: float | None
    unrealized_pnl: float | None
    realized_pnl: float
    dividends: float
    xirr_pct: float | None
    usdinr: float | None
    allocation_by_class: dict[str, float]
    allocation_by_currency: dict[str, float]
    allocation_by_sector: dict[str, float]
    priced_instruments: int
    unpriced_instruments: int


class ImportSummary(BaseModel):
    batch_id: str
    imported: int
    skipped_duplicates: int
    errors: list[str]
    detected_format: str = "generic"
