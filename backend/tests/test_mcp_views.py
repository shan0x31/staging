import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.auth import Setting
from app.models.market import PriceBar
from app.models.portfolio import Account, Instrument, Transaction
from app.services import mcp_views as views


@pytest.fixture()
def portfolio(db_session):
    from app.crypto.keys import key_manager

    key_manager.initialize(db_session, "test-passphrase")
    acct = Account(name="Zerodha", account_number="SECRET-123")
    inst = Instrument(symbol="TCS.NS", name="TCS", sector="IT",
                      currency="INR", country="IN")
    db_session.add_all([acct, inst])
    db_session.flush()
    today = date.today()
    db_session.add_all([
        Transaction(account_id=acct.id, instrument_id=inst.id, type="buy",
                    trade_date=today - timedelta(days=90),
                    quantity=Decimal(10), price=Decimal(3000)),
        PriceBar(instrument_id=inst.id, bar_date=today - timedelta(days=1), close=3500.0),
        PriceBar(instrument_id=inst.id, bar_date=today, close=3600.0),
    ])
    db_session.commit()
    return db_session, inst


def test_privacy_mode_default_on_hides_absolutes(portfolio):
    db, _ = portfolio
    summary = views.portfolio_summary_view(db)
    assert summary["privacy_mode"] is True
    assert "total_value" not in summary and "invested" not in summary
    assert summary["allocation_by_class_pct"] == {"equity": 100.0}
    assert summary["unrealized_pnl_pct"] == 20.0  # 3000 -> 3600

    holdings = views.holdings_view(db)
    assert holdings[0]["weight_pct"] == 100.0
    assert "quantity" not in holdings[0]
    assert "avg_cost" not in holdings[0]
    assert "current_value" not in holdings[0]

    txns = views.transactions_view(db)
    assert txns[0]["symbol"] == "TCS.NS"
    assert "quantity" not in txns[0] and "price" not in txns[0]

    # nothing in the serialized payloads leaks the absolute position
    blob = json.dumps([summary, holdings, txns])
    assert "30000" not in blob and "36000" not in blob and "SECRET-123" not in blob


def test_privacy_off_reveals_values(portfolio):
    db, _ = portfolio
    db.add(Setting(key="privacy_mode", value_json="false"))
    db.commit()

    summary = views.portfolio_summary_view(db)
    assert summary["privacy_mode"] is False
    assert summary["total_value"] == 36000.0
    assert summary["invested"] == 30000.0

    holdings = views.holdings_view(db)
    assert holdings[0]["quantity"] == 10.0
    assert holdings[0]["avg_cost"] == 3000.0

    txns = views.transactions_view(db, symbol="TCS.NS")
    assert txns[0]["quantity"] == 10.0 and txns[0]["price"] == 3000.0


def test_market_snapshot_public_data(portfolio):
    db, _ = portfolio
    snap = views.market_snapshot_view(db)
    assert snap[0]["symbol"] == "TCS.NS"
    assert snap[0]["day_change_pct"] == round((3600 - 3500) / 3500 * 100, 2)


def test_recommendations_view_latest_run_only(portfolio):
    db, _ = portfolio
    from sqlalchemy import select

    from app.models.reco import Recommendation
    from app.services.recommendations.engine import run_recommendation_engine

    n_first = run_recommendation_engine(db)
    run_recommendation_engine(db)  # second run supersedes the first
    recos = views.recommendations_view(db)
    assert recos, "expected at least the concentration finding"
    total_rows = len(db.execute(select(Recommendation)).scalars().all())
    assert total_rows == n_first * 2
    assert len(recos) == n_first  # only the latest run is exposed
    titles = [r["title"] for r in recos]
    assert any("TCS.NS" in t for t in titles)


def test_mcp_server_tools_registered():
    from app import mcp_server

    tool_names = {t: None for t in (
        "get_portfolio_summary", "get_holdings", "get_recommendations",
        "search_transactions", "get_market_snapshot")}
    for name in tool_names:
        assert hasattr(mcp_server, name)
