"""Portfolio-health rules. Every draft explains itself: title + rationale +
the numbers it used. Signals, never orders — the user decides.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models.auth import Setting
from ..portfolio import Holding, to_base_f

SINGLE_STOCK_LIMIT_PCT = 15.0
SECTOR_LIMIT_PCT = 30.0
SINGLE_CURRENCY_INFO_PCT = 90.0
DRIFT_THRESHOLD_PP = 5.0
TLH_LOSS_PCT = 10.0
LTCG_WINDOW_DAYS = (300, 365)  # lots approaching India's 12-month LTCG boundary


@dataclass
class RecoDraft:
    kind: str
    category: str
    severity: str
    title: str
    rationale: str
    instrument_id: int | None = None
    data: dict | None = None


def _get_setting(db: Session, key: str) -> dict | None:
    row = db.get(Setting, key)
    return json.loads(row.value_json) if row else None


def _values(holdings: dict[int, Holding],
            prices: dict[int, tuple[date, float]],
            usdinr: float | None = None, base: str = "INR") -> dict[int, float]:
    """Position values converted to the base currency so weights are comparable
    across INR/USD holdings. Unconvertible currencies are excluded from weights."""
    out = {}
    for iid, h in holdings.items():
        if h.quantity > 0 and iid in prices:
            converted = to_base_f(float(h.quantity) * prices[iid][1],
                                  h.instrument.currency, base, usdinr)
            if converted is not None:
                out[iid] = converted
    return out


def check_concentration(holdings, prices, usdinr: float | None = None,
                        base: str = "INR") -> list[RecoDraft]:
    values = _values(holdings, prices, usdinr, base)
    total = sum(values.values())
    drafts: list[RecoDraft] = []
    if total <= 0:
        return drafts
    for iid, value in values.items():
        pct = value / total * 100
        if pct > SINGLE_STOCK_LIMIT_PCT:
            inst = holdings[iid].instrument
            drafts.append(RecoDraft(
                kind="concentration.single_stock",
                category="portfolio_health",
                severity="warning" if pct < 25 else "action",
                instrument_id=iid,
                title=f"{inst.symbol} is {pct:.1f}% of your equity portfolio",
                rationale=(
                    f"A single stock above {SINGLE_STOCK_LIMIT_PCT:.0f}% concentrates "
                    f"idiosyncratic risk. Consider trimming or pausing further adds."),
                data={"weight_pct": round(pct, 2), "limit_pct": SINGLE_STOCK_LIMIT_PCT},
            ))
    # sector
    sector_totals: dict[str, float] = {}
    for iid, value in values.items():
        sector = holdings[iid].instrument.sector or "Unclassified"
        sector_totals[sector] = sector_totals.get(sector, 0) + value
    for sector, value in sector_totals.items():
        pct = value / total * 100
        if sector != "Unclassified" and pct > SECTOR_LIMIT_PCT:
            drafts.append(RecoDraft(
                kind="concentration.sector",
                category="portfolio_health",
                severity="warning",
                title=f"{sector} sector is {pct:.1f}% of your equity portfolio",
                rationale=f"Sector weight above {SECTOR_LIMIT_PCT:.0f}% amplifies a single theme's drawdowns.",
                data={"sector": sector, "weight_pct": round(pct, 2)},
            ))
    return drafts


def check_currency_exposure(holdings, prices, usdinr: float | None = None,
                            base: str = "INR") -> list[RecoDraft]:
    values = _values(holdings, prices, usdinr, base)
    total = sum(values.values())
    if total <= 0:
        return []
    by_ccy: dict[str, float] = {}
    for iid, value in values.items():
        ccy = holdings[iid].instrument.currency
        by_ccy[ccy] = by_ccy.get(ccy, 0) + value
    for ccy, value in by_ccy.items():
        pct = value / total * 100
        if pct > SINGLE_CURRENCY_INFO_PCT and len(by_ccy) >= 1:
            other = "US" if ccy == "INR" else "Indian"
            return [RecoDraft(
                kind="exposure.currency",
                category="portfolio_health",
                severity="info",
                title=f"{pct:.0f}% of equity is in {ccy}",
                rationale=(f"Geographic/currency diversification via {other} equities can "
                           f"reduce single-economy risk. Informational — depends on your goals."),
                data={"currency": ccy, "weight_pct": round(pct, 2)},
            )]
    return []


def check_allocation_drift(db: Session, class_values: dict[str, float]) -> list[RecoDraft]:
    target = _get_setting(db, "target_allocation")
    if not target:
        return []
    total = sum(class_values.values())
    if total <= 0:
        return []
    drafts = []
    for cls, target_pct in target.items():
        actual_pct = class_values.get(cls, 0) / total * 100
        drift = actual_pct - float(target_pct)
        if abs(drift) > DRIFT_THRESHOLD_PP:
            direction = "overweight" if drift > 0 else "underweight"
            drafts.append(RecoDraft(
                kind="allocation.drift",
                category="portfolio_health",
                severity="action",
                title=f"{cls} is {direction} by {abs(drift):.1f}pp vs your target",
                rationale=(f"Target {target_pct}%, actual {actual_pct:.1f}%. "
                           f"Rebalancing restores your chosen risk profile."),
                data={"asset_class": cls, "target_pct": float(target_pct),
                      "actual_pct": round(actual_pct, 2), "drift_pp": round(drift, 2)},
            ))
    return drafts


def check_tax_flags(holdings, prices, today: date | None = None) -> list[RecoDraft]:
    """India-equity tax awareness: LTCG boundary + loss-harvesting candidates."""
    today = today or date.today()
    drafts: list[RecoDraft] = []
    fy_end_window = today.month in (1, 2, 3)  # Indian FY ends 31 March
    for iid, h in holdings.items():
        if h.quantity <= 0 or iid not in prices:
            continue
        if h.instrument.country != "IN" or h.instrument.asset_class not in {"equity", "etf"}:
            continue
        price = Decimal(str(prices[iid][1]))
        # lots approaching the 12-month LTCG boundary with gains
        approaching = [
            lot for lot in h.lots
            if LTCG_WINDOW_DAYS[0] <= (today - lot.acquired).days < LTCG_WINDOW_DAYS[1]
            and price > lot.unit_cost
        ]
        if approaching:
            days_left = min(365 - (today - lot.acquired).days for lot in approaching)
            drafts.append(RecoDraft(
                kind="tax.ltcg_boundary",
                category="tax",
                severity="info",
                instrument_id=iid,
                title=f"{h.instrument.symbol}: gains turn long-term in ~{days_left} days",
                rationale=("Selling before 12 months triggers STCG at 20%; after 12 months "
                           "LTCG at 12.5% (above the annual exemption). If you plan to sell, "
                           "the boundary matters."),
                data={"lots": len(approaching), "days_to_ltcg": days_left},
            ))
        # tax-loss harvesting
        invested = h.invested
        value = h.quantity * price
        if invested > 0:
            loss_pct = float((value - invested) / invested * 100)
            if loss_pct < -TLH_LOSS_PCT:
                drafts.append(RecoDraft(
                    kind="tax.loss_harvest",
                    category="tax",
                    severity="warning" if fy_end_window else "info",
                    instrument_id=iid,
                    title=f"{h.instrument.symbol} sits {abs(loss_pct):.1f}% below cost",
                    rationale=("Realizing the loss can offset taxable gains this FY"
                               + (" (FY ends 31 March — window closing)." if fy_end_window else ".")
                               + " Re-entry timing is your call; India has no wash-sale rule, "
                                 "but same-day buybacks may be treated as speculative."),
                    data={"unrealized_pct": round(loss_pct, 2), "fy_end_window": fy_end_window},
                ))
    return drafts
