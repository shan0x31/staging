import pytest

from app.crypto.keys import KeyringLockedError, WrongPassphraseError, key_manager


def test_initialize_and_roundtrip(db_session):
    key_manager.initialize(db_session, "hunter2hunter2")
    token = key_manager.encrypt_str("42.5 shares of RELIANCE")
    assert token.startswith("enc1:")
    assert "RELIANCE" not in token
    assert key_manager.decrypt_str(token) == "42.5 shares of RELIANCE"


def test_unlock_after_lock(db_session):
    key_manager.initialize(db_session, "hunter2hunter2")
    token = key_manager.encrypt_str("secret")
    key_manager.lock()
    with pytest.raises(KeyringLockedError):
        key_manager.decrypt_str(token)
    key_manager.unlock(db_session, "hunter2hunter2")
    assert key_manager.decrypt_str(token) == "secret"


def test_wrong_passphrase_rejected(db_session):
    key_manager.initialize(db_session, "hunter2hunter2")
    key_manager.lock()
    with pytest.raises(WrongPassphraseError):
        key_manager.unlock(db_session, "wrong-passphrase")
    assert not key_manager.unlocked


def test_short_passphrase_rejected(db_session):
    with pytest.raises(ValueError):
        key_manager.initialize(db_session, "short")


def test_double_initialize_rejected(db_session):
    key_manager.initialize(db_session, "hunter2hunter2")
    with pytest.raises(ValueError):
        key_manager.initialize(db_session, "another-pass")


def test_rotate_passphrase_keeps_data(db_session):
    key_manager.initialize(db_session, "old-passphrase")
    token = key_manager.encrypt_str("still readable")
    key_manager.rotate_passphrase(db_session, "old-passphrase", "new-passphrase")
    key_manager.lock()
    with pytest.raises(WrongPassphraseError):
        key_manager.unlock(db_session, "old-passphrase")
    key_manager.unlock(db_session, "new-passphrase")
    assert key_manager.decrypt_str(token) == "still readable"


def test_unique_nonces(db_session):
    key_manager.initialize(db_session, "hunter2hunter2")
    assert key_manager.encrypt_str("same") != key_manager.encrypt_str("same")
