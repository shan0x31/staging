"""Data views consumed by the MCP server (and testable without MCP).

Privacy mode (settings key `privacy_mode`, DEFAULT ON) is the data-leak
firewall for Claude conversations: Claude sees structure — weights, ratios,
percentage P&L, signals — but no absolute currency amounts, quantities, or
account numbers. The user must explicitly set privacy_mode=false to share
absolute values.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from ..models.auth import Setting
from ..models.market import PriceBar
from ..models.portfolio import Transaction
from ..models.reco import Recommendation
from . import portfolio as psvc

DISCLAIMER = ("Data is informational; recommendations are rule-generated signals, "
              "not investment advice.")


def privacy_on(db: Session) -> bool:
    row = db.get(Setting, "privacy_mode")
    if row is None:
        return True  # private by default
    return bool(json.loads(row.value_json))


def portfolio_summary_view(db: Session) -> dict:
    private = privacy_on(db)
    holdings = psvc.build_holdings(db)
    prices = psvc.latest_prices(db, list(holdings.keys()))

    total = 0.0
    invested = 0.0
    by_class: dict[str, float] = {}
    by_ccy: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    for iid, h in holdings.items():
        if h.quantity <= 0 or iid not in prices:
            continue
        v = float(h.quantity) * prices[iid][1]
        total += v
        invested += float(h.invested)
        by_class[h.instrument.asset_class] = by_class.get(h.instrument.asset_class, 0) + v
        by_ccy[h.instrument.currency] = by_ccy.get(h.instrument.currency, 0) + v
        sector = h.instrument.sector or "Unclassified"
        by_sector[sector] = by_sector.get(sector, 0) + v
    for asset in psvc.manual_assets_total(db):
        v = float(asset.current_value)
        total += v
        by_class[asset.asset_class] = by_class.get(asset.asset_class, 0) + v
        by_ccy[asset.currency] = by_ccy.get(asset.currency, 0) + v

    def pct(d: dict[str, float]) -> dict[str, float]:
        s = sum(d.values())
        return {k: round(v / s * 100, 1) for k, v in sorted(d.items(), key=lambda kv: -kv[1])} if s else {}

    rate = psvc.portfolio_xirr(db, holdings, prices)
    out: dict = {
        "privacy_mode": private,
        "positions": sum(1 for h in holdings.values() if h.quantity > 0),
        "allocation_by_class_pct": pct(by_class),
        "allocation_by_currency_pct": pct(by_ccy),
        "allocation_by_sector_pct": pct(by_sector),
        "xirr_pct": round(rate * 100, 2) if rate is not None else None,
        "unrealized_pnl_pct": round((total - invested) / invested * 100, 2) if invested else None,
        "disclaimer": DISCLAIMER,
    }
    if not private:
        out["total_value"] = round(total, 2)
        out["invested"] = round(invested, 2)
    return out


def holdings_view(db: Session) -> list[dict]:
    private = privacy_on(db)
    holdings = psvc.build_holdings(db)
    prices = psvc.latest_prices(db, list(holdings.keys()))
    total = sum(float(h.quantity) * prices[i][1]
                for i, h in holdings.items() if h.quantity > 0 and i in prices)
    rows = []
    for iid, h in holdings.items():
        if h.quantity <= 0:
            continue
        row: dict = {
            "symbol": h.instrument.symbol,
            "name": h.instrument.name,
            "asset_class": h.instrument.asset_class,
            "sector": h.instrument.sector,
            "currency": h.instrument.currency,
        }
        if iid in prices:
            value = float(h.quantity) * prices[iid][1]
            invested = float(h.invested)
            row["weight_pct"] = round(value / total * 100, 2) if total else None
            row["unrealized_pnl_pct"] = (
                round((value - invested) / invested * 100, 2) if invested else None)
            row["price_date"] = str(prices[iid][0])
        if not private:
            row["quantity"] = float(h.quantity)
            row["avg_cost"] = float(h.avg_cost)
            row["current_value"] = round(float(h.quantity) * prices[iid][1], 2) if iid in prices else None
        rows.append(row)
    rows.sort(key=lambda r: -(r.get("weight_pct") or 0))
    return rows


def recommendations_view(db: Session) -> list[dict]:
    rows = db.execute(
        select(Recommendation)
        .options(joinedload(Recommendation.instrument))
        .order_by(desc(Recommendation.created_at), Recommendation.id)
    ).scalars().all()
    if not rows:
        return []
    latest = rows[0].run_id
    out = []
    for r in rows:
        if r.run_id != latest or r.dismissed:
            continue
        out.append({
            "created_at": str(r.created_at),
            "kind": r.kind,
            "category": r.category,
            "severity": r.severity,
            "symbol": r.instrument.symbol if r.instrument else None,
            "title": r.title,
            "rationale": r.rationale,
        })
    return out


def transactions_view(db: Session, symbol: str | None = None, limit: int = 50) -> list[dict]:
    private = privacy_on(db)
    stmt = (select(Transaction)
            .options(joinedload(Transaction.instrument))
            .order_by(desc(Transaction.trade_date), desc(Transaction.id))
            .limit(min(limit, 200)))
    rows = db.execute(stmt).scalars().all()
    out = []
    for t in rows:
        sym = t.instrument.symbol if t.instrument else None
        if symbol and sym != symbol:
            continue
        row: dict = {"date": str(t.trade_date), "type": t.type, "symbol": sym}
        if not private:
            row.update({
                "quantity": float(t.quantity) if t.quantity is not None else None,
                "price": float(t.price) if t.price is not None else None,
                "amount": float(t.amount) if t.amount is not None else None,
            })
        out.append(row)
    return out


def market_snapshot_view(db: Session) -> list[dict]:
    """Day moves for held instruments — public prices, so no privacy gating."""
    holdings = psvc.build_holdings(db)
    out = []
    for iid, h in holdings.items():
        if h.quantity <= 0:
            continue
        bars = db.execute(
            select(PriceBar).where(PriceBar.instrument_id == iid)
            .order_by(desc(PriceBar.bar_date)).limit(2)
        ).scalars().all()
        if len(bars) < 2 or not bars[1].close:
            continue
        out.append({
            "symbol": h.instrument.symbol,
            "close": bars[0].close,
            "as_of": str(bars[0].bar_date),
            "day_change_pct": round((bars[0].close - bars[1].close) / bars[1].close * 100, 2),
        })
    out.sort(key=lambda r: -abs(r["day_change_pct"]))
    return out
