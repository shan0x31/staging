from datetime import date
from decimal import Decimal

import pytest

from app.models.portfolio import Account, Instrument, Transaction
from app.services.portfolio import build_holdings, xirr


@pytest.fixture()
def seeded(db_session):
    from app.crypto.keys import key_manager

    key_manager.initialize(db_session, "test-passphrase")
    acct = Account(name="Zerodha", currency="INR", country="IN")
    inst = Instrument(symbol="RELIANCE.NS", name="Reliance Industries",
                      exchange="NSE", currency="INR", country="IN")
    db_session.add_all([acct, inst])
    db_session.flush()
    return db_session, acct, inst


def _txn(acct, inst, **kw):
    defaults = dict(account_id=acct.id, instrument_id=inst.id if inst else None)
    defaults.update(kw)
    return Transaction(**defaults)


def test_fifo_avg_cost_and_realized(seeded):
    db, acct, inst = seeded
    db.add_all([
        _txn(acct, inst, type="buy", trade_date=date(2024, 1, 10),
             quantity=Decimal(10), price=Decimal(100)),
        _txn(acct, inst, type="buy", trade_date=date(2024, 2, 10),
             quantity=Decimal(10), price=Decimal(200)),
        _txn(acct, inst, type="sell", trade_date=date(2024, 3, 10),
             quantity=Decimal(15), price=Decimal(250)),
    ])
    db.commit()
    h = build_holdings(db)[inst.id]
    # FIFO: sells 10 @100 cost then 5 @200 cost
    assert h.realized_pnl == Decimal(10) * 150 + Decimal(5) * 50
    assert h.quantity == 5
    assert h.avg_cost == Decimal(200)


def test_fees_capitalized_on_buy(seeded):
    db, acct, inst = seeded
    db.add(_txn(acct, inst, type="buy", trade_date=date(2024, 1, 1),
                quantity=Decimal(10), price=Decimal(100), fees=Decimal(50)))
    db.commit()
    h = build_holdings(db)[inst.id]
    assert h.avg_cost == Decimal(105)


def test_split_adjusts_lots(seeded):
    db, acct, inst = seeded
    db.add_all([
        _txn(acct, inst, type="buy", trade_date=date(2024, 1, 1),
             quantity=Decimal(10), price=Decimal(1000)),
        _txn(acct, inst, type="split", trade_date=date(2024, 6, 1),
             quantity=Decimal(5)),  # 1:5
    ])
    db.commit()
    h = build_holdings(db)[inst.id]
    assert h.quantity == 50
    assert h.avg_cost == Decimal(200)
    assert h.invested == Decimal(10000)


def test_bonus_zero_cost_lot(seeded):
    db, acct, inst = seeded
    db.add_all([
        _txn(acct, inst, type="buy", trade_date=date(2024, 1, 1),
             quantity=Decimal(10), price=Decimal(100)),
        _txn(acct, inst, type="bonus", trade_date=date(2024, 6, 1),
             quantity=Decimal(10)),  # 1:1 bonus
    ])
    db.commit()
    h = build_holdings(db)[inst.id]
    assert h.quantity == 20
    assert h.invested == Decimal(1000)
    assert h.avg_cost == Decimal(50)


def test_dividends_accumulate(seeded):
    db, acct, inst = seeded
    db.add_all([
        _txn(acct, inst, type="buy", trade_date=date(2024, 1, 1),
             quantity=Decimal(10), price=Decimal(100)),
        _txn(acct, inst, type="dividend", trade_date=date(2024, 5, 1),
             amount=Decimal("123.45")),
    ])
    db.commit()
    h = build_holdings(db)[inst.id]
    assert h.dividends == Decimal("123.45")


def test_fully_exited_position_keeps_realized(seeded):
    db, acct, inst = seeded
    db.add_all([
        _txn(acct, inst, type="buy", trade_date=date(2024, 1, 1),
             quantity=Decimal(10), price=Decimal(100)),
        _txn(acct, inst, type="sell", trade_date=date(2024, 2, 1),
             quantity=Decimal(10), price=Decimal(150)),
    ])
    db.commit()
    h = build_holdings(db)[inst.id]
    assert h.quantity == 0
    assert h.realized_pnl == Decimal(500)


def test_xirr_known_value():
    # 1000 invested, 1100 back one year later -> ~10%
    flows = [(date(2023, 1, 1), -1000.0), (date(2024, 1, 1), 1100.0)]
    rate = xirr(flows)
    assert rate is not None
    assert abs(rate - 0.10) < 0.005


def test_xirr_multiple_flows():
    flows = [
        (date(2022, 1, 1), -1000.0),
        (date(2023, 1, 1), -1000.0),
        (date(2024, 1, 1), 2500.0),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert rate > 0.1


def test_xirr_degenerate_cases():
    assert xirr([]) is None
    assert xirr([(date(2024, 1, 1), -100.0)]) is None
    assert xirr([(date(2024, 1, 1), -100.0), (date(2024, 6, 1), -50.0)]) is None
