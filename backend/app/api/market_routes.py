from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.security import get_current_user
from ..db import get_db
from ..models.auth import User
from ..models.market import PriceBar
from ..models.portfolio import Instrument
from ..services import portfolio as svc
from ..services.marketdata.service import market_data_service
from .deps import require_unlocked

router = APIRouter(prefix="/market", tags=["market"])


class RefreshOut(BaseModel):
    refreshed: int
    bars_upserted: int
    fx_bars: int
    failures: list[str]


class BarOut(BaseModel):
    bar_date: date
    close: float
    open: float | None
    high: float | None
    low: float | None
    volume: float | None


class MoverOut(BaseModel):
    symbol: str
    name: str
    close: float
    prev_close: float
    change_pct: float


@router.post("/refresh", response_model=RefreshOut)
def refresh_now(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Manual refresh. Public data only — works even with a locked keyring."""
    report = market_data_service.refresh_all(db)
    fx = market_data_service.refresh_fx(db)
    return RefreshOut(refreshed=report.refreshed, bars_upserted=report.bars_upserted,
                      fx_bars=fx, failures=report.failures)


@router.get("/prices/{instrument_id}", response_model=list[BarOut])
def get_prices(instrument_id: int, days: int = 365,
               db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if db.get(Instrument, instrument_id) is None:
        raise HTTPException(404, "Instrument not found")
    cutoff = date.today() - timedelta(days=days)
    bars = db.execute(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument_id, PriceBar.bar_date >= cutoff)
        .order_by(PriceBar.bar_date)
    ).scalars().all()
    return [BarOut(bar_date=b.bar_date, close=b.close, open=b.open,
                   high=b.high, low=b.low, volume=b.volume) for b in bars]


@router.get("/status")
def market_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    n_instruments = db.execute(select(func.count(Instrument.id))).scalar_one()
    n_bars = db.execute(select(func.count(PriceBar.id))).scalar_one()
    latest = db.execute(select(func.max(PriceBar.bar_date))).scalar_one()
    return {"instruments": n_instruments, "price_bars": n_bars, "latest_bar_date": latest}


@router.get("/movers", response_model=list[MoverOut])
def top_movers(db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    """Day change for held instruments (needs holdings, hence unlock)."""
    holdings = svc.build_holdings(db)
    movers: list[MoverOut] = []
    for iid, h in holdings.items():
        if h.quantity <= 0:
            continue
        bars = db.execute(
            select(PriceBar).where(PriceBar.instrument_id == iid)
            .order_by(PriceBar.bar_date.desc()).limit(2)
        ).scalars().all()
        if len(bars) < 2 or not bars[1].close:
            continue
        change = (bars[0].close - bars[1].close) / bars[1].close * 100
        movers.append(MoverOut(symbol=h.instrument.symbol, name=h.instrument.name,
                               close=bars[0].close, prev_close=bars[1].close,
                               change_pct=round(change, 2)))
    movers.sort(key=lambda m: -abs(m.change_pct))
    return movers
