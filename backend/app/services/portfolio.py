"""Holdings math: transactions ledger -> FIFO lots, P&L, XIRR, allocations.

Encrypted columns force computation in Python; at personal-portfolio scale
(thousands of rows) this is milliseconds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models.market import FxRate, PriceBar
from ..models.portfolio import Instrument, ManualAsset, Transaction

ZERO = Decimal(0)


@dataclass
class Lot:
    quantity: Decimal
    unit_cost: Decimal
    acquired: date
    account_id: int


@dataclass
class SaleRecord:
    """One FIFO lot consumption by a sell — the atom of capital-gains reporting."""
    instrument: Instrument
    quantity: Decimal
    sell_date: date
    sell_price: Decimal
    acquire_date: date
    unit_cost: Decimal

    @property
    def proceeds(self) -> Decimal:
        return self.quantity * self.sell_price

    @property
    def cost(self) -> Decimal:
        return self.quantity * self.unit_cost

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.cost

    @property
    def holding_days(self) -> int:
        return (self.sell_date - self.acquire_date).days

    @property
    def long_term(self) -> bool:
        # India listed equity/ETF/MF(equity): >12 months. US: >1 year. Same boundary.
        return self.holding_days > 365


@dataclass
class Holding:
    instrument: Instrument
    lots: list[Lot] = field(default_factory=list)
    realized_pnl: Decimal = ZERO
    dividends: Decimal = ZERO
    fees: Decimal = ZERO
    sales: list[SaleRecord] = field(default_factory=list)

    @property
    def quantity(self) -> Decimal:
        return sum((l.quantity for l in self.lots), ZERO)

    @property
    def invested(self) -> Decimal:
        return sum((l.quantity * l.unit_cost for l in self.lots), ZERO)

    @property
    def avg_cost(self) -> Decimal:
        q = self.quantity
        return (self.invested / q) if q else ZERO


class LedgerError(ValueError):
    pass


def build_holdings(db: Session) -> dict[int, Holding]:
    """Replay the ledger into per-instrument holdings with FIFO lots."""
    txns = db.execute(
        select(Transaction)
        .where(Transaction.instrument_id.isnot(None))
        .options(joinedload(Transaction.instrument))
        .order_by(Transaction.trade_date, Transaction.id)
    ).scalars().all()

    holdings: dict[int, Holding] = {}
    for t in txns:
        h = holdings.setdefault(t.instrument_id, Holding(instrument=t.instrument))
        if t.type == "buy":
            qty, price = t.quantity or ZERO, t.price or ZERO
            fees = t.fees or ZERO
            unit_cost = price + (fees / qty if qty else ZERO)  # fees capitalized into cost
            h.lots.append(Lot(qty, unit_cost, t.trade_date, t.account_id))
        elif t.type == "sell":
            remaining = t.quantity or ZERO
            proceeds_per_share = t.price or ZERO
            h.fees += t.fees or ZERO
            while remaining > 0 and h.lots:
                lot = h.lots[0]
                take = min(lot.quantity, remaining)
                h.realized_pnl += take * (proceeds_per_share - lot.unit_cost)
                h.sales.append(SaleRecord(
                    instrument=t.instrument, quantity=take,
                    sell_date=t.trade_date, sell_price=proceeds_per_share,
                    acquire_date=lot.acquired, unit_cost=lot.unit_cost))
                lot.quantity -= take
                remaining -= take
                if lot.quantity == 0:
                    h.lots.pop(0)
            if remaining > 0:
                # Oversell: ledger incomplete (missing buys). Record P&L on
                # zero-cost basis rather than crash; surfaced via notes/audit later.
                h.realized_pnl += remaining * proceeds_per_share
                h.sales.append(SaleRecord(
                    instrument=t.instrument, quantity=remaining,
                    sell_date=t.trade_date, sell_price=proceeds_per_share,
                    acquire_date=t.trade_date, unit_cost=ZERO))
        elif t.type == "split":
            factor = t.quantity or Decimal(1)
            if factor <= 0:
                raise LedgerError(f"Invalid split factor {factor}")
            for lot in h.lots:
                lot.quantity *= factor
                lot.unit_cost /= factor
        elif t.type == "bonus":
            h.lots.append(Lot(t.quantity or ZERO, ZERO, t.trade_date, t.account_id))
        elif t.type == "dividend":
            h.dividends += t.amount or ZERO
        elif t.type == "fee":
            h.fees += t.amount or ZERO
    return {iid: h for iid, h in holdings.items() if h.quantity > 0 or h.realized_pnl or h.dividends}


def latest_prices(db: Session, instrument_ids: list[int]) -> dict[int, tuple[date, float]]:
    if not instrument_ids:
        return {}
    rows = db.execute(
        select(PriceBar)
        .where(PriceBar.instrument_id.in_(instrument_ids))
        .order_by(PriceBar.instrument_id, PriceBar.bar_date)
    ).scalars().all()
    out: dict[int, tuple[date, float]] = {}
    for bar in rows:  # ordered by date asc -> last write wins
        out[bar.instrument_id] = (bar.bar_date, bar.close)
    return out


def latest_fx(db: Session, pair: str = "USDINR") -> float | None:
    row = db.execute(
        select(FxRate).where(FxRate.pair == pair).order_by(FxRate.rate_date.desc())
    ).scalars().first()
    return row.rate if row else None


def to_base(amount: Decimal, currency: str, base: str, usdinr: float | None) -> Decimal | None:
    """Convert between INR and USD aggregates. Returns None when no rate is known."""
    if currency == base:
        return amount
    if usdinr is None:
        return None
    rate = Decimal(str(usdinr))
    if currency == "USD" and base == "INR":
        return amount * rate
    if currency == "INR" and base == "USD":
        return amount / rate
    return None


def to_base_f(amount: float, currency: str, base: str, usdinr: float | None) -> float | None:
    """Float variant of to_base for aggregate/weight math."""
    converted = to_base(Decimal(str(amount)), currency, base, usdinr)
    return float(converted) if converted is not None else None


# -- XIRR ----------------------------------------------------------------------

def xirr(cashflows: list[tuple[date, float]], guess: float = 0.1) -> float | None:
    """Annualized IRR of dated cashflows (negative = outflow/investment).
    Newton with bisection fallback; None if it cannot converge."""
    if len(cashflows) < 2:
        return None
    flows = sorted(cashflows)
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    t0 = flows[0][0]
    years = [(d - t0).days / 365.25 for d, _ in flows]
    amounts = [a for _, a in flows]

    def npv(rate: float) -> float:
        return sum(a / (1 + rate) ** y for a, y in zip(amounts, years))

    def dnpv(rate: float) -> float:
        return sum(-y * a / (1 + rate) ** (y + 1) for a, y in zip(amounts, years))

    rate = guess
    for _ in range(50):
        f = npv(rate)
        if abs(f) < 1e-8:
            return rate
        d = dnpv(rate)
        if d == 0:
            break
        step = f / d
        rate -= step
        if rate <= -0.999:
            break
        if abs(step) < 1e-10:
            return rate

    lo, hi = -0.999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-8:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def portfolio_xirr(db: Session, holdings: dict[int, Holding],
                   prices: dict[int, tuple[date, float]],
                   base: str = "INR", usdinr: float | None = None) -> float | None:
    """XIRR over all instrument cashflows plus current value as terminal inflow.
    Flows are converted to the base currency at the latest FX rate (an
    approximation vs trade-date rates, but sign- and magnitude-correct);
    instruments whose currency cannot be converted are excluded entirely."""
    if usdinr is None:
        usdinr = latest_fx(db)
    txns = db.execute(
        select(Transaction)
        .where(Transaction.instrument_id.isnot(None))
        .options(joinedload(Transaction.instrument))
    ).scalars().all()
    flows: list[tuple[date, float]] = []
    skipped_instruments: set[int] = set()
    for t in txns:
        ccy = t.instrument.currency
        if t.type == "buy":
            native = -float((t.quantity or ZERO) * (t.price or ZERO) + (t.fees or ZERO))
        elif t.type == "sell":
            native = float((t.quantity or ZERO) * (t.price or ZERO) - (t.fees or ZERO))
        elif t.type == "dividend":
            native = float(t.amount or ZERO)
        else:
            continue
        converted = to_base_f(native, ccy, base, usdinr)
        if converted is None:
            skipped_instruments.add(t.instrument_id)
            continue
        flows.append((t.trade_date, converted))
    current_value = 0.0
    for iid, h in holdings.items():
        if iid in prices and h.quantity > 0 and iid not in skipped_instruments:
            value = to_base_f(float(h.quantity) * prices[iid][1],
                              h.instrument.currency, base, usdinr)
            if value is not None:
                current_value += value
    if current_value > 0:
        flows.append((date.today(), current_value))
    return xirr(flows)


# -- summary ---------------------------------------------------------------------

def manual_assets_total(db: Session) -> list[ManualAsset]:
    return db.execute(select(ManualAsset)).scalars().all()
