import io
from datetime import date


def _seed_position(client):
    acct = client.post("/accounts", json={"name": "Zerodha", "currency": "INR"}).json()
    inst = client.post("/instruments", json={
        "symbol": "TCS.NS", "name": "Tata Consultancy Services",
        "exchange": "NSE", "sector": "IT", "currency": "INR", "country": "IN",
    }).json()
    r = client.post("/transactions", json={
        "account_id": acct["id"], "instrument_id": inst["id"], "type": "buy",
        "trade_date": "2024-01-10", "quantity": "10", "price": "3500",
    })
    assert r.status_code == 201, r.text
    return acct, inst


def test_crud_and_holdings_flow(authed_client):
    acct, inst = _seed_position(authed_client)

    holdings = authed_client.get("/portfolio/holdings").json()
    assert len(holdings) == 1
    h = holdings[0]
    assert h["quantity"] == 10.0
    assert h["avg_cost"] == 3500.0
    assert h["current_price"] is None  # no price bars yet

    summary = authed_client.get("/portfolio/summary").json()
    assert summary["unpriced_instruments"] == 1
    assert summary["invested"] == 35000.0


def test_locked_keyring_blocks_data_routes(authed_client):
    _seed_position(authed_client)
    authed_client.post("/auth/lock")
    assert authed_client.get("/portfolio/holdings").status_code == 423
    assert authed_client.get("/accounts").status_code == 423
    authed_client.post("/auth/unlock", json={"passphrase": "battery-staple"})
    assert authed_client.get("/portfolio/holdings").status_code == 200


def test_csv_import_endpoint(authed_client):
    csv_bytes = (
        "date,type,symbol,quantity,price,account\n"
        "2024-01-10,buy,INFY.NS,20,1500,Zerodha\n"
    ).encode()
    r = authed_client.post(
        "/transactions/import",
        files={"file": ("txns.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 1 and body["errors"] == []

    holdings = authed_client.get("/portfolio/holdings").json()
    assert holdings[0]["instrument"]["symbol"] == "INFY.NS"


def test_account_with_transactions_cannot_be_deleted(authed_client):
    acct, _ = _seed_position(authed_client)
    r = authed_client.delete(f"/accounts/{acct['id']}")
    assert r.status_code == 409


def test_manual_assets_crud(authed_client):
    r = authed_client.post("/manual-assets", json={
        "name": "HDFC FD", "asset_class": "fd", "currency": "INR",
        "invested": "100000", "current_value": "104500", "as_of": str(date.today()),
    })
    assert r.status_code == 201
    asset = r.json()
    assert float(asset["current_value"]) == 104500.0

    listed = authed_client.get("/manual-assets").json()
    assert len(listed) == 1

    r = authed_client.delete(f"/manual-assets/{asset['id']}")
    assert r.status_code == 204
    assert authed_client.get("/manual-assets").json() == []


def test_encrypted_at_rest(authed_client, db_engine):
    """Raw DB rows must not contain plaintext quantities or account numbers."""
    from sqlalchemy import text

    acct = authed_client.post("/accounts", json={
        "name": "Secret Broker", "currency": "INR", "account_number": "AB-12345-Z",
    }).json()
    inst = authed_client.post("/instruments", json={
        "symbol": "SBIN.NS", "name": "State Bank of India",
    }).json()
    authed_client.post("/transactions", json={
        "account_id": acct["id"], "instrument_id": inst["id"], "type": "buy",
        "trade_date": "2024-01-10", "quantity": "777", "price": "601.55",
    })

    with db_engine.connect() as conn:
        raw_acct = conn.execute(text("SELECT account_number FROM accounts WHERE name='Secret Broker'")).scalar()
        assert raw_acct.startswith("enc1:")
        assert "AB-12345-Z" not in raw_acct

        raw_qty, raw_price = conn.execute(
            text("SELECT quantity, price FROM transactions ORDER BY id DESC LIMIT 1")).one()
        assert raw_qty.startswith("enc1:") and raw_price.startswith("enc1:")
        assert "777" not in raw_qty and "601.55" not in raw_price
