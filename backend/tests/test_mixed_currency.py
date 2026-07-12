"""Regression tests for mixed INR/USD portfolios (found in live smoke test):
raw native sums made USD positions look ~95x smaller than reality."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.market import FxRate, PriceBar
from app.models.portfolio import Account, Instrument, Transaction
from app.services.portfolio import build_holdings, latest_prices, portfolio_xirr
from app.services.recommendations.rules import check_concentration, check_currency_exposure

USDINR = 90.0


@pytest.fixture()
def mixed(db_session):
    from app.crypto.keys import key_manager

    key_manager.initialize(db_session, "test-passphrase")
    zerodha = Account(name="Zerodha", currency="INR", country="IN")
    fidelity = Account(name="Fidelity", currency="USD", country="US")
    tcs = Instrument(symbol="TCS.NS", name="TCS", currency="INR", country="IN")
    aapl = Instrument(symbol="AAPL", name="Apple", currency="USD", country="US")
    db_session.add_all([zerodha, fidelity, tcs, aapl])
    db_session.flush()
    today = date.today()
    year_ago = today - timedelta(days=365)
    db_session.add_all([
        # INR: 10 * 3000 = 30,000 INR invested, now 33,000 INR
        Transaction(account_id=zerodha.id, instrument_id=tcs.id, type="buy",
                    trade_date=year_ago, quantity=Decimal(10), price=Decimal(3000)),
        # USD: 10 * 100 = 1,000 USD invested, now 1,200 USD (= 108,000 INR, dominant)
        Transaction(account_id=fidelity.id, instrument_id=aapl.id, type="buy",
                    trade_date=year_ago, quantity=Decimal(10), price=Decimal(100)),
        PriceBar(instrument_id=tcs.id, bar_date=today, close=3300.0),
        PriceBar(instrument_id=aapl.id, bar_date=today, close=120.0),
        FxRate(pair="USDINR", rate_date=today, rate=USDINR),
    ])
    db_session.commit()
    return db_session, tcs, aapl


def test_concentration_uses_converted_weights(mixed):
    db, tcs, aapl = mixed
    holdings = build_holdings(db)
    prices = latest_prices(db, list(holdings.keys()))
    drafts = check_concentration(holdings, prices, usdinr=USDINR)
    # Converted: AAPL 108k / 141k = 76.6%, TCS 33k / 141k = 23.4% — both above
    # the 15% limit. Pre-fix, raw native sums gave AAPL 1.2k/34.2k = 3.5% (missed)
    # and TCS 96.5%.
    singles = {d.instrument_id: d for d in drafts if d.kind == "concentration.single_stock"}
    assert set(singles) == {aapl.id, tcs.id}
    assert 75 < singles[aapl.id].data["weight_pct"] < 78
    assert 22 < singles[tcs.id].data["weight_pct"] < 25
    assert singles[aapl.id].severity == "action"   # > 25%
    assert singles[tcs.id].severity == "warning"   # 15–25%


def test_currency_exposure_uses_converted_weights(mixed):
    db, tcs, aapl = mixed
    holdings = build_holdings(db)
    prices = latest_prices(db, list(holdings.keys()))
    # Neither currency exceeds 90% after conversion -> no finding
    assert check_currency_exposure(holdings, prices, usdinr=USDINR) == []
    # Without conversion this would have (wrongly) reported INR ~96%


def test_xirr_positive_for_all_gaining_mixed_portfolio(mixed):
    db, *_ = mixed
    holdings = build_holdings(db)
    prices = latest_prices(db, list(holdings.keys()))
    rate = portfolio_xirr(db, holdings, prices, base="INR", usdinr=USDINR)
    assert rate is not None
    # Both legs gained (+10% INR, +20% USD) over ~1y; XIRR must be solidly positive
    assert 0.08 < rate < 0.25


def test_summary_endpoint_consistent_currency_split(mixed, db_engine):
    db, *_ = mixed
    from app.services import mcp_views

    summary = mcp_views.portfolio_summary_view(db)
    ccy = summary["allocation_by_currency_pct"]
    assert 75 < ccy["USD"] < 78
    assert 22 < ccy["INR"] < 25
    assert summary["unrealized_pnl_pct"] > 0
