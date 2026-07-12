from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.market import PriceBar
from app.models.portfolio import Account, Instrument, Transaction
from app.services.portfolio import build_holdings, latest_prices
from app.services.recommendations.engine import run_recommendation_engine
from app.services.recommendations.rules import (
    check_concentration,
    check_tax_flags,
)


@pytest.fixture()
def portfolio(db_session):
    from app.crypto.keys import key_manager

    key_manager.initialize(db_session, "test-passphrase")
    acct = Account(name="Zerodha", currency="INR", country="IN")
    big = Instrument(symbol="RELIANCE.NS", name="Reliance", sector="Energy",
                     currency="INR", country="IN")
    small = Instrument(symbol="INFY.NS", name="Infosys", sector="IT",
                       currency="INR", country="IN")
    db_session.add_all([acct, big, small])
    db_session.flush()
    today = date.today()
    db_session.add_all([
        Transaction(account_id=acct.id, instrument_id=big.id, type="buy",
                    trade_date=today - timedelta(days=330),
                    quantity=Decimal(100), price=Decimal(2000)),
        Transaction(account_id=acct.id, instrument_id=small.id, type="buy",
                    trade_date=today - timedelta(days=100),
                    quantity=Decimal(10), price=Decimal(1500)),
        PriceBar(instrument_id=big.id, bar_date=today, close=2500.0),
        PriceBar(instrument_id=small.id, bar_date=today, close=1200.0),
    ])
    db_session.commit()
    return db_session, acct, big, small


def test_concentration_rule_fires(portfolio):
    db, acct, big, small = portfolio
    holdings = build_holdings(db)
    prices = latest_prices(db, list(holdings.keys()))
    drafts = check_concentration(holdings, prices)
    kinds = {d.kind for d in drafts}
    assert "concentration.single_stock" in kinds  # RELIANCE ~95% of equity
    reliance_draft = next(d for d in drafts if d.instrument_id == big.id)
    assert reliance_draft.severity == "action"
    assert reliance_draft.data["weight_pct"] > 90


def test_ltcg_boundary_flag(portfolio):
    db, acct, big, small = portfolio
    holdings = build_holdings(db)
    prices = latest_prices(db, list(holdings.keys()))
    drafts = check_tax_flags(holdings, prices)
    ltcg = [d for d in drafts if d.kind == "tax.ltcg_boundary"]
    assert len(ltcg) == 1  # RELIANCE bought 330 days ago with a gain
    assert ltcg[0].instrument_id == big.id
    assert 0 < ltcg[0].data["days_to_ltcg"] <= 65


def test_tax_loss_harvest_flag(portfolio):
    db, acct, big, small = portfolio
    holdings = build_holdings(db)
    prices = latest_prices(db, list(holdings.keys()))
    drafts = check_tax_flags(holdings, prices)
    tlh = [d for d in drafts if d.kind == "tax.loss_harvest"]
    assert len(tlh) == 1  # INFY -20% vs cost
    assert tlh[0].instrument_id == small.id
    assert tlh[0].data["unrealized_pct"] == -20.0


def test_engine_persists_encrypted_run(portfolio, db_engine):
    db, *_ = portfolio
    count = run_recommendation_engine(db)
    assert count >= 3

    from sqlalchemy import text

    with db_engine.connect() as conn:
        raw = conn.execute(text("SELECT title, rationale FROM recommendations LIMIT 1")).one()
        assert raw.title.startswith("enc1:")
        assert raw.rationale.startswith("enc1:")
        assert "RELIANCE" not in raw.title


def test_recommendations_api_flow(authed_client, db_engine):
    acct = authed_client.post("/accounts", json={"name": "Zerodha"}).json()
    inst = authed_client.post("/instruments", json={
        "symbol": "RELIANCE.NS", "name": "Reliance", "sector": "Energy",
    }).json()
    authed_client.post("/transactions", json={
        "account_id": acct["id"], "instrument_id": inst["id"], "type": "buy",
        "trade_date": str(date.today() - timedelta(days=30)),
        "quantity": "10", "price": "2000",
    })
    from sqlalchemy import text

    with db_engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO price_bars (instrument_id, bar_date, close) "
            f"VALUES ({inst['id']}, '{date.today()}', 2500)"))

    run = authed_client.post("/recommendations/run").json()
    assert run["generated"] >= 1
    assert "not investment advice" in run["disclaimer"]

    recos = authed_client.get("/recommendations").json()
    assert len(recos) == run["generated"]
    assert all(r["run_id"] == run["run_id"] for r in recos)
    single = next(r for r in recos if r["kind"] == "concentration.single_stock")
    assert single["symbol"] == "RELIANCE.NS"

    r = authed_client.post(f"/recommendations/{single['id']}/dismiss")
    assert r.status_code == 200
    remaining = authed_client.get("/recommendations").json()
    assert all(x["id"] != single["id"] for x in remaining)


def test_allocation_drift_via_settings(authed_client, db_engine):
    acct = authed_client.post("/accounts", json={"name": "Zerodha"}).json()
    inst = authed_client.post("/instruments", json={
        "symbol": "NIFTYBEES.NS", "name": "Nifty ETF", "asset_class": "etf",
    }).json()
    authed_client.post("/transactions", json={
        "account_id": acct["id"], "instrument_id": inst["id"], "type": "buy",
        "trade_date": "2024-01-01", "quantity": "100", "price": "200",
    })
    from sqlalchemy import text

    with db_engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO price_bars (instrument_id, bar_date, close) "
            f"VALUES ({inst['id']}, '{date.today()}', 250)"))

    r = authed_client.put("/settings/target_allocation", json={"value": {"etf": 50, "fd": 50}})
    assert r.status_code == 200

    run = authed_client.post("/recommendations/run").json()
    recos = authed_client.get("/recommendations").json()
    drift = [x for x in recos if x["kind"] == "allocation.drift"]
    assert len(drift) == 2  # etf overweight, fd underweight
    assert {d["data"]["asset_class"] for d in drift} == {"etf", "fd"}


def test_settings_whitelist(authed_client):
    r = authed_client.put("/settings/evil_key", json={"value": 1})
    assert r.status_code == 422
