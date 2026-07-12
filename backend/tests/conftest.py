import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as app_db
from app.crypto.keys import key_manager


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    app_db.Base.metadata.drop_all(engine)
    from app import models  # noqa: F401

    app_db.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def reset_key_manager():
    key_manager.lock()
    yield
    key_manager.lock()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    from app.auth import security

    security._attempts.clear()
    yield
    security._attempts.clear()


@pytest.fixture()
def client(db_engine, monkeypatch):
    """TestClient wired to the in-memory DB."""
    TestSession = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(app_db, "engine", db_engine)
    monkeypatch.setattr(app_db, "SessionLocal", TestSession)

    from app.main import create_app
    from app.db import get_db

    application = create_app()

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = override_get_db
    # Bypass lifespan (init_db would hit the real engine binding).
    with TestClient(application) as c:
        yield c


@pytest.fixture()
def authed_client(client):
    """Client with setup done, logged in, and keyring unlocked."""
    r = client.post("/auth/setup", json={
        "username": "owner",
        "password": "correct-horse",
        "encryption_passphrase": "battery-staple",
    })
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
