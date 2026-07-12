from datetime import date
from decimal import Decimal

import pytest

from app.models.portfolio import Account, Instrument, Transaction
from app.services.reports import capital_gains_report, dividends_report, fy_of_date_india


@pytest.fixture()
def ledger(db_session):
    from app.crypto.keys import key_manager

    key_manager.initialize(db_session, "test-passphrase")
    acct = Account(name="Zerodha", currency="INR", country="IN")
    rel = Instrument(symbol="RELIANCE.NS", name="Reliance", currency="INR", country="IN")
    aapl = Instrument(symbol="AAPL", name="Apple", currency="USD", country="US")
    db_session.add_all([acct, rel, aapl])
    db_session.flush()

    def txn(inst, **kw):
        db_session.add(Transaction(account_id=acct.id, instrument_id=inst.id, **kw))

    # India: bought Jan-2024 (100 sh @2000). Sold 40 in June-2025 (LT, +40k),
    # bought 50 more May-2025 @2800, sold 30 in Feb-2026 (ST from the May lot
    # after the first lot's remainder... FIFO: June sell consumes first lot).
    txn(rel, type="buy", trade_date=date(2024, 1, 15), quantity=Decimal(100), price=Decimal(2000))
    txn(rel, type="sell", trade_date=date(2025, 6, 20), quantity=Decimal(40), price=Decimal(3000))
    txn(rel, type="buy", trade_date=date(2025, 5, 10), quantity=Decimal(50), price=Decimal(2800))
    txn(rel, type="sell", trade_date=date(2026, 2, 10), quantity=Decimal(70), price=Decimal(3100))
    txn(rel, type="dividend", trade_date=date(2025, 8, 1), amount=Decimal(900))
    txn(rel, type="dividend", trade_date=date(2024, 8, 1), amount=Decimal(750))
    # US: short-term sale in calendar 2025
    txn(aapl, type="buy", trade_date=date(2025, 3, 1), quantity=Decimal(10), price=Decimal(200))
    txn(aapl, type="sell", trade_date=date(2025, 10, 1), quantity=Decimal(10), price=Decimal(250))
    txn(aapl, type="dividend", trade_date=date(2025, 5, 15), amount=Decimal(25))
    db_session.commit()
    return db_session


def test_fy_of_date():
    assert fy_of_date_india(date(2025, 3, 31)) == 2024
    assert fy_of_date_india(date(2025, 4, 1)) == 2025


def test_india_fy_2025_gains(ledger):
    report = capital_gains_report(ledger, 2025, basis="fy_in")
    assert report["period"] == "FY2025-26"
    # FY2025-26 sales: June-2025 sell of 40 (acquired Jan-2024, 522d -> LT, gain 40*1000)
    # Feb-2026 sell of 70: FIFO consumes remaining 60 of lot1 (LT, 60*1100)
    # then 10 of the May-2025 lot (276d -> ST, 10*300)
    assert report["long_term_gain"] == 40 * 1000 + 60 * 1100
    assert report["short_term_gain"] == 10 * 300
    assert report["sale_count"] == 3
    terms = [r["term"] for r in report["records"]]
    assert terms == ["long", "long", "short"]
    # exemption context present for India: LTCG 1,06,000 < 1,25,000 exemption
    assert report["ltcg_exemption_inr"] == 125_000
    assert report["ltcg_above_exemption"] == 0.0


def test_india_fy_2024_empty(ledger):
    report = capital_gains_report(ledger, 2024, basis="fy_in")
    assert report["sale_count"] == 0
    assert report["long_term_gain"] == 0 and report["short_term_gain"] == 0


def test_us_calendar_gains(ledger):
    report = capital_gains_report(ledger, 2025, basis="calendar_us")
    assert report["period"] == "2025" and report["currency"] == "USD"
    assert report["short_term_gain"] == 500.0  # 10 * (250-200), 214 days
    assert report["long_term_gain"] == 0.0
    assert report["records"][0]["symbol"] == "AAPL"


def test_dividends_fy_report(ledger):
    report = dividends_report(ledger, 2025, basis="fy_in")
    assert report["total"] == 900.0  # only the Aug-2025 dividend is in FY2025-26
    assert report["by_instrument"][0]["symbol"] == "RELIANCE.NS"

    prev = dividends_report(ledger, 2024, basis="fy_in")
    assert prev["total"] == 750.0

    us = dividends_report(ledger, 2025, basis="calendar_us")
    assert us["total"] == 25.0


def test_reports_api(authed_client):
    acct = authed_client.post("/accounts", json={"name": "Zerodha"}).json()
    inst = authed_client.post("/instruments", json={"symbol": "TCS.NS", "name": "TCS"}).json()
    for body in [
        {"type": "buy", "trade_date": "2024-01-10", "quantity": "10", "price": "3000"},
        {"type": "sell", "trade_date": "2025-06-10", "quantity": "10", "price": "4000"},
    ]:
        r = authed_client.post("/transactions", json={
            "account_id": acct["id"], "instrument_id": inst["id"], **body})
        assert r.status_code == 201

    report = authed_client.get("/reports/capital-gains?year=2025&basis=fy_in").json()
    assert report["long_term_gain"] == 10000.0
    assert report["short_term_gain"] == 0.0

    periods = authed_client.get("/reports/periods").json()
    assert 2025 in periods["fy_in"] and 2023 in periods["fy_in"]

    assert authed_client.get("/reports/capital-gains?year=2025&basis=bogus").status_code == 422
