from datetime import date, timedelta


def _seed_priced_holding(client, db_engine):
    from sqlalchemy import text

    acct = client.post("/accounts", json={"name": "Zerodha"}).json()
    inst = client.post("/instruments", json={"symbol": "TCS.NS", "name": "TCS"}).json()
    client.post("/transactions", json={
        "account_id": acct["id"], "instrument_id": inst["id"], "type": "buy",
        "trade_date": "2024-01-10", "quantity": "10", "price": "3500",
    })
    today = date.today()
    with db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO price_bars (instrument_id, bar_date, close) VALUES "
            f"({inst['id']}, '{today - timedelta(days=1)}', 3600),"
            f"({inst['id']}, '{today}', 3708)"
        ))
    return inst


def test_prices_endpoint(authed_client, db_engine):
    inst = _seed_priced_holding(authed_client, db_engine)
    bars = authed_client.get(f"/market/prices/{inst['id']}").json()
    assert len(bars) == 2
    assert bars[-1]["close"] == 3708

    assert authed_client.get("/market/prices/9999").status_code == 404


def test_movers_and_priced_summary(authed_client, db_engine):
    _seed_priced_holding(authed_client, db_engine)

    movers = authed_client.get("/market/movers").json()
    assert len(movers) == 1
    assert movers[0]["symbol"] == "TCS.NS"
    assert movers[0]["change_pct"] == 3.0  # 3600 -> 3708

    holdings = authed_client.get("/portfolio/holdings").json()
    assert holdings[0]["current_price"] == 3708
    assert holdings[0]["current_value"] == 37080.0
    assert holdings[0]["unrealized_pnl"] == 2080.0

    summary = authed_client.get("/portfolio/summary").json()
    assert summary["equity_value"] == 37080.0
    assert summary["priced_instruments"] == 1
    assert summary["net_worth"] == 37080.0


def test_market_status(authed_client, db_engine):
    _seed_priced_holding(authed_client, db_engine)
    status = authed_client.get("/market/status").json()
    assert status["instruments"] == 1
    assert status["price_bars"] == 2
