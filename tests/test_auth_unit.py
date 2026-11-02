from pathlib import Path
import pytest

from law_rag.auth import AuthError, AuthStore


def test_register_and_authenticate_user(tmp_path: Path) -> None:
    store = AuthStore(db_path=tmp_path / "users.db", secret_key="test-secret", token_ttl_seconds=3600)

    session = store.register_user("  Alice@Example.com ", "password123")
    assert session.user.id == 1
    assert session.user.email == "alice@example.com"
    assert session.token

    verified = store.verify_token(session.token)
    assert verified.id == 1
    assert verified.email == "alice@example.com"

    login_session = store.authenticate_user("ALICE@example.com", "password123")
    assert login_session.user.id == 1
    assert login_session.user.email == "alice@example.com"


def test_register_rejects_duplicate_email(tmp_path: Path) -> None:
    store = AuthStore(db_path=tmp_path / "users.db", secret_key="test-secret")
    store.register_user("user@example.com", "password123")

    with pytest.raises(AuthError) as exc_info:
        store.register_user("USER@example.com", "anotherpass123")
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "email_already_registered"


def test_register_validates_email_and_password(tmp_path: Path) -> None:
    store = AuthStore(db_path=tmp_path / "users.db", secret_key="test-secret")

    with pytest.raises(AuthError) as email_exc:
        store.register_user("not-an-email", "password123")
    assert email_exc.value.status_code == 400
    assert email_exc.value.code == "invalid_email"

    with pytest.raises(AuthError) as pass_exc:
        store.register_user("valid@example.com", "short")
    assert pass_exc.value.status_code == 400
    assert pass_exc.value.code == "weak_password"


def test_authenticate_rejects_wrong_credentials(tmp_path: Path) -> None:
    store = AuthStore(db_path=tmp_path / "users.db", secret_key="test-secret")
    store.register_user("user@example.com", "password123")

    with pytest.raises(AuthError) as wrong_pass:
        store.authenticate_user("user@example.com", "wrongpassword")
    assert wrong_pass.value.status_code == 401
    assert wrong_pass.value.code == "invalid_credentials"

    with pytest.raises(AuthError) as unknown_user:
        store.authenticate_user("nobody@example.com", "password123")
    assert unknown_user.value.status_code == 401
    assert unknown_user.value.code == "invalid_credentials"


def test_verify_token_rejects_tampered_or_expired_tokens(tmp_path: Path) -> None:
    store = AuthStore(db_path=tmp_path / "users.db", secret_key="test-secret", token_ttl_seconds=-10)
    expired_session = store.register_user("user@example.com", "password123")

    with pytest.raises(AuthError) as expired_exc:
        store.verify_token(expired_session.token)
    assert expired_exc.value.status_code == 401
    assert expired_exc.value.code == "authentication_required"

    valid_store = AuthStore(db_path=tmp_path / "users.db", secret_key="test-secret", token_ttl_seconds=3600)
    valid_session = valid_store.authenticate_user("user@example.com", "password123")

    with pytest.raises(AuthError) as tampered_exc:
        valid_store.verify_token(valid_session.token + "tampered")
    assert tampered_exc.value.status_code == 401
    assert tampered_exc.value.code == "authentication_required"
