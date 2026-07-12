from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models.auth import User
from ..services import portfolio as svc
from .deps import require_unlocked
from .schemas import HoldingOut, InstrumentOut, PortfolioSummary

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/holdings", response_model=list[HoldingOut])
def get_holdings(db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    holdings = svc.build_holdings(db)
    prices = svc.latest_prices(db, list(holdings.keys()))
    out: list[HoldingOut] = []
    for iid, h in holdings.items():
        if h.quantity <= 0:
            continue
        price_info = prices.get(iid)
        qty, invested = float(h.quantity), float(h.invested)
        current_value = unrealized = unrealized_pct = None
        if price_info:
            current_value = qty * price_info[1]
            unrealized = current_value - invested
            unrealized_pct = (unrealized / invested * 100) if invested else None
        out.append(HoldingOut(
            instrument=InstrumentOut.model_validate(h.instrument),
            quantity=qty,
            avg_cost=float(h.avg_cost),
            invested=invested,
            current_price=price_info[1] if price_info else None,
            price_date=price_info[0] if price_info else None,
            current_value=current_value,
            unrealized_pnl=unrealized,
            unrealized_pnl_pct=unrealized_pct,
            realized_pnl=float(h.realized_pnl),
            dividends=float(h.dividends),
        ))
    out.sort(key=lambda h: -(h.current_value or 0))
    return out


@router.get("/summary", response_model=PortfolioSummary)
def get_summary(db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    base = settings.base_currency
    usdinr = svc.latest_fx(db, "USDINR")
    holdings = svc.build_holdings(db)
    prices = svc.latest_prices(db, list(holdings.keys()))

    equity_value = Decimal(0)
    invested_total = Decimal(0)
    realized = Decimal(0)
    dividends = Decimal(0)
    unpriced = 0
    conversion_gap = False
    alloc_class: dict[str, float] = {}
    alloc_ccy: dict[str, float] = {}
    alloc_sector: dict[str, float] = {}

    for iid, h in holdings.items():
        realized += h.realized_pnl
        dividends += h.dividends
        if h.quantity <= 0:
            continue
        ccy = h.instrument.currency
        inv_base = svc.to_base(h.invested, ccy, base, usdinr)
        if inv_base is not None:
            invested_total += inv_base
        price_info = prices.get(iid)
        if not price_info:
            unpriced += 1
            continue
        value = h.quantity * Decimal(str(price_info[1]))
        value_base = svc.to_base(value, ccy, base, usdinr)
        if value_base is None:
            conversion_gap = True
            continue
        equity_value += value_base
        v = float(value_base)
        cls = h.instrument.asset_class
        alloc_class[cls] = alloc_class.get(cls, 0) + v
        alloc_ccy[ccy] = alloc_ccy.get(ccy, 0) + v
        sector = h.instrument.sector or "Unclassified"
        alloc_sector[sector] = alloc_sector.get(sector, 0) + v

    manual_total = Decimal(0)
    for asset in svc.manual_assets_total(db):
        v_base = svc.to_base(asset.current_value, asset.currency, base, usdinr)
        if v_base is None:
            conversion_gap = True
            continue
        manual_total += v_base
        v = float(v_base)
        alloc_class[asset.asset_class] = alloc_class.get(asset.asset_class, 0) + v
        alloc_ccy[asset.currency] = alloc_ccy.get(asset.currency, 0) + v

    total = equity_value + manual_total
    priced = len([1 for iid in holdings if iid in prices])

    def pct(d: dict[str, float]) -> dict[str, float]:
        s = sum(d.values())
        return {k: round(v / s * 100, 2) for k, v in d.items()} if s else {}

    rate = svc.portfolio_xirr(db, holdings, prices, base=base, usdinr=usdinr)
    unrealized_total = (equity_value - invested_total) if not conversion_gap and priced else None
    return PortfolioSummary(
        base_currency=base,
        net_worth=float(total) if not conversion_gap else None,
        equity_value=float(equity_value),
        manual_assets_value=float(manual_total),
        invested=float(invested_total),
        unrealized_pnl=float(unrealized_total) if unrealized_total is not None else None,
        realized_pnl=float(realized),
        dividends=float(dividends),
        xirr_pct=round(rate * 100, 2) if rate is not None else None,
        usdinr=usdinr,
        allocation_by_class=pct(alloc_class),
        allocation_by_currency=pct(alloc_ccy),
        allocation_by_sector=pct(alloc_sector),
        priced_instruments=priced,
        unpriced_instruments=unpriced,
    )
