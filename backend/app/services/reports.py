"""Tax-year reports: realized capital gains and dividend income.

India: financial year Apr 1 – Mar 31 ("FY2025-26"); listed equity held >12
months is long-term (LTCG 12.5% above the annual exemption — 1.25L as of
FY2024-25 — else STCG 20%). US instruments use the same >1 year long-term
boundary on a calendar-year basis. Figures are informational, not tax advice —
exchange-specific charges, grandfathering (pre-2018), and slab rules are out
of scope for v1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models.portfolio import Transaction
from .portfolio import SaleRecord, build_holdings

LTCG_EXEMPTION_INR = 125_000


def fy_bounds_india(fy_start_year: int) -> tuple[date, date]:
    return date(fy_start_year, 4, 1), date(fy_start_year + 1, 3, 31)


def fy_label_india(fy_start_year: int) -> str:
    return f"FY{fy_start_year}-{str(fy_start_year + 1)[-2:]}"


def fy_of_date_india(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


@dataclass
class GainsBucket:
    short_term: Decimal = Decimal(0)
    long_term: Decimal = Decimal(0)
    proceeds: Decimal = Decimal(0)
    records: list[dict] = field(default_factory=list)


def _record_dict(s: SaleRecord) -> dict:
    return {
        "symbol": s.instrument.symbol,
        "name": s.instrument.name,
        "currency": s.instrument.currency,
        "country": s.instrument.country,
        "quantity": float(s.quantity),
        "acquire_date": s.acquire_date.isoformat(),
        "sell_date": s.sell_date.isoformat(),
        "holding_days": s.holding_days,
        "term": "long" if s.long_term else "short",
        "unit_cost": float(s.unit_cost),
        "sell_price": float(s.sell_price),
        "cost": float(s.cost),
        "proceeds": float(s.proceeds),
        "gain": float(s.gain),
    }


def capital_gains_report(db: Session, year: int, basis: str = "fy_in") -> dict:
    """basis="fy_in": Indian FY (year = FY start, e.g. 2025 => Apr'25–Mar'26),
    IN-listed instruments. basis="calendar_us": calendar year, US instruments."""
    if basis == "fy_in":
        start, end = fy_bounds_india(year)
        period_label = fy_label_india(year)
        country = "IN"
    elif basis == "calendar_us":
        start, end = date(year, 1, 1), date(year, 12, 31)
        period_label = str(year)
        country = "US"
    else:
        raise ValueError("basis must be fy_in or calendar_us")

    holdings = build_holdings(db)
    bucket = GainsBucket()
    for h in holdings.values():
        if h.instrument.country != country:
            continue
        for s in h.sales:
            if not (start <= s.sell_date <= end):
                continue
            bucket.records.append(_record_dict(s))
            bucket.proceeds += s.proceeds
            if s.long_term:
                bucket.long_term += s.gain
            else:
                bucket.short_term += s.gain
    bucket.records.sort(key=lambda r: r["sell_date"])

    out = {
        "basis": basis,
        "period": period_label,
        "country": country,
        "currency": "INR" if country == "IN" else "USD",
        "short_term_gain": float(bucket.short_term),
        "long_term_gain": float(bucket.long_term),
        "total_proceeds": float(bucket.proceeds),
        "sale_count": len(bucket.records),
        "records": bucket.records,
        "disclaimer": ("Informational summary from your ledger — not tax advice. "
                       "Verify against broker/CA statements before filing."),
    }
    if country == "IN":
        taxable_ltcg = max(float(bucket.long_term) - LTCG_EXEMPTION_INR, 0.0)
        out["ltcg_exemption_inr"] = LTCG_EXEMPTION_INR
        out["ltcg_above_exemption"] = taxable_ltcg
    return out


def dividends_report(db: Session, year: int, basis: str = "fy_in") -> dict:
    if basis == "fy_in":
        start, end = fy_bounds_india(year)
        period_label = fy_label_india(year)
    elif basis == "calendar_us":
        start, end = date(year, 1, 1), date(year, 12, 31)
        period_label = str(year)
    else:
        raise ValueError("basis must be fy_in or calendar_us")

    txns = db.execute(
        select(Transaction)
        .where(Transaction.type == "dividend",
               Transaction.trade_date >= start,
               Transaction.trade_date <= end)
        .options(joinedload(Transaction.instrument))
        .order_by(Transaction.trade_date)
    ).scalars().all()

    country = "IN" if basis == "fy_in" else "US"
    by_instrument: dict[str, dict] = {}
    total = Decimal(0)
    rows = []
    for t in txns:
        if t.instrument is None or t.instrument.country != country:
            continue
        amount = t.amount or Decimal(0)
        total += amount
        rows.append({
            "date": t.trade_date.isoformat(),
            "symbol": t.instrument.symbol,
            "amount": float(amount),
        })
        agg = by_instrument.setdefault(
            t.instrument.symbol, {"symbol": t.instrument.symbol, "total": 0.0, "count": 0})
        agg["total"] += float(amount)
        agg["count"] += 1

    return {
        "basis": basis,
        "period": period_label,
        "country": country,
        "currency": "INR" if country == "IN" else "USD",
        "total": float(total),
        "by_instrument": sorted(by_instrument.values(), key=lambda r: -r["total"]),
        "records": rows,
    }
