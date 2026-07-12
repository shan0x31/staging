"""Price refresh orchestration.

Privacy property: refresh reads only the public `instruments` table and writes
public `price_bars`/`fx_rates`, so it needs no keyring unlock and leaks nothing
about position sizes to providers (every known instrument is refreshed, held
or not).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models.market import FxRate, PriceBar
from ...models.portfolio import Instrument
from .amfi import AmfiProvider
from .base import Bar, QuoteProvider
from .yahoo import YahooProvider

log = logging.getLogger(__name__)


@dataclass
class RefreshReport:
    refreshed: int = 0
    bars_upserted: int = 0
    failures: list[str] = field(default_factory=list)


class MarketDataService:
    def __init__(self, yahoo: QuoteProvider | None = None, amfi: QuoteProvider | None = None):
        self._yahoo = yahoo or YahooProvider()
        self._amfi = amfi or AmfiProvider()

    def provider_for(self, symbol: str) -> QuoteProvider:
        return self._amfi if symbol.startswith("MF:") else self._yahoo

    def refresh_instrument(self, db: Session, instrument: Instrument, days: int = 400) -> int:
        bars = self.provider_for(instrument.symbol).get_daily_bars(instrument.symbol, days)
        if not bars:
            return 0
        existing = {
            d for (d,) in db.execute(
                select(PriceBar.bar_date).where(PriceBar.instrument_id == instrument.id)
            )
        }
        added = 0
        cutoff = date.today() - timedelta(days=days)
        for bar in bars:
            if bar.bar_date < cutoff:
                continue
            if bar.bar_date in existing:
                continue
            db.add(PriceBar(
                instrument_id=instrument.id, bar_date=bar.bar_date,
                open=bar.open, high=bar.high, low=bar.low,
                close=bar.close, volume=bar.volume,
            ))
            added += 1
        db.commit()
        return added

    def refresh_all(self, db: Session, country: str | None = None, days: int = 400) -> RefreshReport:
        stmt = select(Instrument)
        if country:
            stmt = stmt.where(Instrument.country == country)
        instruments = db.execute(stmt).scalars().all()
        report = RefreshReport()
        for inst in instruments:
            try:
                report.bars_upserted += self.refresh_instrument(db, inst, days)
                report.refreshed += 1
            except Exception as exc:  # one bad symbol must not sink the batch
                db.rollback()
                log.warning("refresh failed for %s: %s", inst.symbol, exc)
                report.failures.append(f"{inst.symbol}: {exc}")
        return report

    def refresh_fx(self, db: Session, days: int = 400) -> int:
        bars: list[Bar] = self._yahoo.get_daily_bars("USDINR=X", days)
        existing = {
            d for (d,) in db.execute(select(FxRate.rate_date).where(FxRate.pair == "USDINR"))
        }
        added = 0
        for bar in bars:
            if bar.bar_date in existing:
                continue
            db.add(FxRate(pair="USDINR", rate_date=bar.bar_date, rate=bar.close))
            added += 1
        db.commit()
        return added


market_data_service = MarketDataService()
