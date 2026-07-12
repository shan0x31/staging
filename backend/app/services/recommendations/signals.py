"""Instrument-level quant signals for held positions."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models.market import PriceBar
from ..portfolio import Holding
from .rules import RecoDraft
from .technicals import crossover, momentum_12_1, pct_from_52w_extremes, rsi

RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
NEAR_EXTREME_PCT = 2.0


def _closes(db: Session, instrument_id: int, limit: int = 420) -> list[float]:
    rows = db.execute(
        select(PriceBar.close)
        .where(PriceBar.instrument_id == instrument_id)
        .order_by(PriceBar.bar_date.desc())
        .limit(limit)
    ).scalars().all()
    return list(reversed(rows))


def instrument_signals(db: Session, holdings: dict[int, Holding]) -> list[RecoDraft]:
    drafts: list[RecoDraft] = []
    for iid, h in holdings.items():
        if h.quantity <= 0:
            continue
        closes = _closes(db, iid)
        if len(closes) < 30:
            continue
        symbol = h.instrument.symbol

        cross = crossover(closes)
        if cross == "golden":
            drafts.append(RecoDraft(
                kind="signal.golden_cross", category="signal", severity="info",
                instrument_id=iid,
                title=f"{symbol}: 50-DMA crossed above 200-DMA",
                rationale="A golden cross is a trend-following buy signal; it lags price and can whipsaw.",
                data={"signal": "golden_cross"}))
        elif cross == "death":
            drafts.append(RecoDraft(
                kind="signal.death_cross", category="signal", severity="warning",
                instrument_id=iid,
                title=f"{symbol}: 50-DMA crossed below 200-DMA",
                rationale="A death cross flags trend deterioration in a holding — worth a review.",
                data={"signal": "death_cross"}))

        r = rsi(closes)
        if r is not None:
            if r > RSI_OVERBOUGHT:
                drafts.append(RecoDraft(
                    kind="signal.rsi_overbought", category="signal", severity="info",
                    instrument_id=iid,
                    title=f"{symbol}: RSI {r:.0f} (overbought)",
                    rationale="Stretched short-term momentum; pullbacks are common from here.",
                    data={"rsi": round(r, 1)}))
            elif r < RSI_OVERSOLD:
                drafts.append(RecoDraft(
                    kind="signal.rsi_oversold", category="signal", severity="info",
                    instrument_id=iid,
                    title=f"{symbol}: RSI {r:.0f} (oversold)",
                    rationale="Heavy short-term selling; mean-reversion setups often start here.",
                    data={"rsi": round(r, 1)}))

        extremes = pct_from_52w_extremes(closes)
        if extremes:
            below_high, above_low = extremes
            if below_high <= NEAR_EXTREME_PCT:
                drafts.append(RecoDraft(
                    kind="signal.near_52w_high", category="signal", severity="info",
                    instrument_id=iid,
                    title=f"{symbol} is within {below_high:.1f}% of its 52-week high",
                    rationale="Strength near highs often persists, but position sizing discipline matters most here.",
                    data={"below_high_pct": round(below_high, 2)}))
            elif above_low <= NEAR_EXTREME_PCT:
                drafts.append(RecoDraft(
                    kind="signal.near_52w_low", category="signal", severity="warning",
                    instrument_id=iid,
                    title=f"{symbol} is within {above_low:.1f}% of its 52-week low",
                    rationale="Persistent weakness — re-check the thesis before averaging down.",
                    data={"above_low_pct": round(above_low, 2)}))

        mom = momentum_12_1(closes)
        if mom is not None and abs(mom) >= 25:
            drafts.append(RecoDraft(
                kind="signal.momentum", category="signal", severity="info",
                instrument_id=iid,
                title=f"{symbol}: 12-1 month momentum {mom:+.0f}%",
                rationale="Cross-sectional momentum is a documented factor; extremes cut both ways.",
                data={"momentum_12_1_pct": round(mom, 1)}))
    return drafts
