from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.portfolio import Account, Instrument, Transaction
from app.services.broker_formats import detect_format
from app.services.importer import import_csv

ZERODHA_CSV = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
RELIANCE,INE002A01018,2024-05-21,NSE,EQ,EQ,buy,false,10,2850.5,200521000001,110052100001,2024-05-21T10:15:31
TCS,INE467B01029,2024-06-14,NSE,EQ,EQ,buy,false,5,3810,200614000002,110061400002,2024-06-14T11:02:12
RELIANCE,INE002A01018,2024-09-02,NSE,EQ,EQ,sell,false,4,3010,200902000003,110090200003,2024-09-02T13:44:55
IRCTC,INE335Y01020,2024-07-10,BSE,EQ,A,buy,false,20,995.25,200710000004,110071000004,2024-07-10T09:31:00
"""

GROWW_CSV = """Stock Name,ISIN,Trade Date,Exchange,Type,Quantity,Price
Tata Motors,INE155A01022,12-03-2024,NSE,Buy,15,950.50
Tata Motors,INE155A01022,20-06-2024,NSE,Sell,5,1010
"""

US_CSV = """Run Date,Action,Symbol,Description,Quantity,Price ($),Commission ($),Amount ($)
09/15/2024,YOU BOUGHT,AAPL,APPLE INC,10,220.10,0.00,-2201.00
10/01/2024,DIVIDEND RECEIVED,AAPL,APPLE INC,,,,2.50
11/20/2024,YOU SOLD,AAPL,APPLE INC,-4,235.00,0.05,939.95
01/05/2024,JOURNALED CASH,,CASH MOVEMENT,,,,500.00
"""


@pytest.fixture()
def unlocked(db_session):
    from app.crypto.keys import key_manager

    key_manager.initialize(db_session, "test-passphrase")
    return db_session


def test_detect_formats():
    assert detect_format(ZERODHA_CSV.splitlines()[0].split(",")) == "zerodha"
    assert detect_format(GROWW_CSV.splitlines()[0].split(",")) == "groww"
    assert detect_format(US_CSV.splitlines()[0].split(",")) == "us_broker"
    assert detect_format(["date", "type", "account", "symbol"]) == "generic"
    assert detect_format(["foo", "bar"]) == "unknown"


def test_zerodha_import(unlocked):
    db = unlocked
    result = import_csv(db, ZERODHA_CSV)
    assert result.detected_format == "zerodha"
    assert result.errors == []
    assert result.imported == 4

    symbols = {i.symbol for i in db.execute(select(Instrument)).scalars()}
    assert symbols == {"RELIANCE.NS", "TCS.NS", "IRCTC.BO"}  # BSE -> .BO
    rel = db.execute(select(Instrument).where(Instrument.symbol == "RELIANCE.NS")).scalars().one()
    assert rel.country == "IN" and rel.currency == "INR"

    acct = db.execute(select(Account)).scalars().one()
    assert acct.name == "Zerodha"

    from app.services.portfolio import build_holdings

    h = build_holdings(db)[rel.id]
    assert h.quantity == Decimal(6)  # 10 bought - 4 sold


def test_zerodha_reimport_skips_duplicates(unlocked):
    db = unlocked
    import_csv(db, ZERODHA_CSV)
    second = import_csv(db, ZERODHA_CSV)
    assert second.imported == 0
    assert second.skipped_duplicates == 4


def test_groww_import_with_custom_account(unlocked):
    db = unlocked
    result = import_csv(db, GROWW_CSV, account="Groww Personal")
    assert result.detected_format == "groww"
    assert result.errors == []
    assert result.imported == 2
    acct = db.execute(select(Account)).scalars().one()
    assert acct.name == "Groww Personal"
    inst = db.execute(select(Instrument)).scalars().one()
    assert inst.symbol.endswith(".NS")
    assert inst.name == "Tata Motors"


def test_us_broker_import(unlocked):
    db = unlocked
    result = import_csv(db, US_CSV)
    assert result.detected_format == "us_broker"
    assert result.errors == []
    assert result.imported == 3  # journal row skipped

    aapl = db.execute(select(Instrument).where(Instrument.symbol == "AAPL")).scalars().one()
    assert aapl.currency == "USD" and aapl.country == "US"

    txns = db.execute(select(Transaction).order_by(Transaction.trade_date)).scalars().all()
    types = [t.type for t in txns]
    assert types == ["buy", "dividend", "sell"]
    buy = txns[0]
    assert buy.trade_date.isoformat() == "2024-09-15"  # MM/DD parsed correctly
    sell = txns[2]
    assert sell.quantity == Decimal(4)  # negative qty normalized
    assert txns[1].amount == Decimal("2.50")


def test_unknown_format_reports_error(unlocked):
    result = import_csv(unlocked, "alpha,beta\n1,2\n")
    assert result.imported == 0
    assert "Unrecognized CSV format" in result.errors[0]


def test_forced_format_override(unlocked):
    # generic template forced explicitly still works
    csv_text = "date,type,symbol,quantity,price,account\n2024-01-10,buy,INFY.NS,5,1500,Zerodha\n"
    result = import_csv(unlocked, csv_text, fmt="generic")
    assert result.imported == 1
