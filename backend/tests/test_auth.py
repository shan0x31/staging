def test_status_before_setup(client):
    r = client.get("/auth/status")
    assert r.status_code == 200
    assert r.json() == {"setup_complete": False, "unlocked": False}


def test_setup_login_flow(client):
    r = client.post("/auth/setup", json={
        "username": "owner",
        "password": "correct-horse",
        "encryption_passphrase": "battery-staple",
    })
    assert r.status_code == 201
    token = r.json()["token"]

    # second setup attempt rejected
    r = client.post("/auth/setup", json={
        "username": "intruder",
        "password": "xxxxxxxx",
        "encryption_passphrase": "yyyyyyyy",
    })
    assert r.status_code == 409

    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "owner"

    r = client.get("/auth/status")
    assert r.json() == {"setup_complete": True, "unlocked": True}


def test_login_wrong_password(authed_client):
    r = authed_client.post("/auth/login", json={"username": "owner", "password": "nope-nope"})
    assert r.status_code == 401


def test_login_and_lock_unlock(authed_client):
    r = authed_client.post("/auth/login", json={"username": "owner", "password": "correct-horse"})
    assert r.status_code == 200

    r = authed_client.post("/auth/lock")
    assert r.status_code == 200
    assert authed_client.get("/auth/status").json()["unlocked"] is False

    r = authed_client.post("/auth/unlock", json={"passphrase": "wrong-passphrase"})
    assert r.status_code == 401

    r = authed_client.post("/auth/unlock", json={"passphrase": "battery-staple"})
    assert r.status_code == 200
    assert authed_client.get("/auth/status").json()["unlocked"] is True


def test_protected_routes_require_auth(client):
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/lock").status_code == 401
    assert client.post("/auth/unlock", json={"passphrase": "x" * 8}).status_code == 401


def test_logout_revokes_session(authed_client):
    r = authed_client.post("/auth/logout")
    assert r.status_code == 200
    assert authed_client.get("/auth/me").status_code == 401


def test_login_rate_limit(authed_client):
    for _ in range(8):
        authed_client.post("/auth/login", json={"username": "owner", "password": "bad-password"})
    r = authed_client.post("/auth/login", json={"username": "owner", "password": "bad-password"})
    assert r.status_code == 429
