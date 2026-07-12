from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.portfolio import Account, Instrument, Transaction
from app.services.importer import import_generic_csv

CSV = """date,type,symbol,name,exchange,asset_class,quantity,price,fees,amount,currency,account,notes
2024-01-10,buy,RELIANCE.NS,Reliance Industries,NSE,equity,10,2450.50,20,,INR,Zerodha,first buy
2024-02-15,buy,AAPL,Apple Inc,NASDAQ,equity,5,182.30,1,,USD,Fidelity,
2024-03-01,dividend,RELIANCE.NS,,,,,,,90.00,INR,Zerodha,
2024-04-01,deposit,,,,,,,,50000,INR,Zerodha,funding
"""


@pytest.fixture()
def unlocked(db_session):
    from app.crypto.keys import key_manager

    key_manager.initialize(db_session, "test-passphrase")
    return db_session


def test_generic_import(unlocked):
    db = unlocked
    result = import_generic_csv(db, CSV)
    assert result.errors == []
    assert result.imported == 4

    accounts = {a.name for a in db.execute(select(Account)).scalars()}
    assert accounts == {"Zerodha", "Fidelity"}

    rel = db.execute(select(Instrument).where(Instrument.symbol == "RELIANCE.NS")).scalars().one()
    assert rel.country == "IN" and rel.currency == "INR" and rel.exchange == "NSE"
    aapl = db.execute(select(Instrument).where(Instrument.symbol == "AAPL")).scalars().one()
    assert aapl.country == "US" and aapl.currency == "USD"

    buys = [t for t in db.execute(select(Transaction)).scalars() if t.type == "buy"]
    assert {float(t.quantity) for t in buys} == {10.0, 5.0}


def test_duplicate_rows_skipped(unlocked):
    db = unlocked
    first = import_generic_csv(db, CSV)
    assert first.imported == 4
    second = import_generic_csv(db, CSV)
    assert second.imported == 0
    assert second.skipped_duplicates == 4


def test_error_rows_reported_others_kept(unlocked):
    db = unlocked
    bad_csv = (
        "date,type,symbol,quantity,price,account\n"
        "2024-01-10,buy,TCS.NS,10,3800,Zerodha\n"
        "not-a-date,buy,INFY.NS,5,1500,Zerodha\n"
        "2024-01-12,frobnicate,WIPRO.NS,5,400,Zerodha\n"
        "2024-01-13,buy,HDFC.NS,,1600,Zerodha\n"
    )
    result = import_generic_csv(db, bad_csv)
    assert result.imported == 1
    assert len(result.errors) == 3
    assert "line 3" in result.errors[0]


def test_missing_columns_rejected(unlocked):
    result = import_generic_csv(unlocked, "foo,bar\n1,2\n")
    assert result.imported == 0
    assert "Missing columns" in result.errors[0]


def test_split_and_bonus_rows(unlocked):
    db = unlocked
    csv_text = (
        "date,type,symbol,quantity,price,account\n"
        "2024-01-10,buy,IRFC.NS,100,30,Zerodha\n"
        "2024-02-10,split,IRFC.NS,2,,Zerodha\n"
        "2024-03-10,bonus,IRFC.NS,50,,Zerodha\n"
    )
    result = import_generic_csv(db, csv_text)
    assert result.errors == []
    from app.services.portfolio import build_holdings

    inst = db.execute(select(Instrument).where(Instrument.symbol == "IRFC.NS")).scalars().one()
    h = build_holdings(db)[inst.id]
    assert h.quantity == Decimal(250)  # 100*2 + 50 bonus
