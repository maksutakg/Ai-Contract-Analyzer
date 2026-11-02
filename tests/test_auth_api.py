from io import BytesIO
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from law_rag.api import create_app


def _docx_bytes(*lines: str) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_register_login_and_me_flow(tmp_path: Path) -> None:
    client = TestClient(create_app(use_fake_clients=True, auth_db_path=tmp_path / "users.db"))

    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "Lawyer@Firm.com", "password": "securepassword"},
    )
    assert reg.status_code == 201
    data = reg.json()
    assert data["user"] == {"id": 1, "email": "lawyer@firm.com"}
    token = data["token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == {"id": 1, "email": "lawyer@firm.com"}

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "lawyer@firm.com", "password": "securepassword"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["email"] == "lawyer@firm.com"


def test_register_duplicate_and_validation_errors(tmp_path: Path) -> None:
    client = TestClient(create_app(use_fake_clients=True, auth_db_path=tmp_path / "users.db"))

    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": "bad-email", "password": "securepassword"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": "user@firm.com", "password": "123"},
        ).status_code
        == 400
    )

    first = client.post(
        "/api/v1/auth/register",
        json={"email": "user@firm.com", "password": "securepassword"},
    )
    assert first.status_code == 201

    dup = client.post(
        "/api/v1/auth/register",
        json={"email": "USER@firm.com", "password": "securepassword"},
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "email_already_registered"


def test_analyze_requires_bearer_token(tmp_path: Path) -> None:
    client = TestClient(create_app(use_fake_clients=True, auth_db_path=tmp_path / "users.db"))
    files = {"file": ("c.docx", _docx_bytes("MADDE 1 - FESIH", "Taraflar derhal fesih hakkina sahiptir."))}

    unauth = client.post("/api/v1/contracts/analyze", files=files)
    assert unauth.status_code == 401
    assert unauth.json()["detail"]["code"] == "authentication_required"

    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "user@firm.com", "password": "securepassword"},
    )
    token = reg.json()["token"]

    authed = client.post(
        "/api/v1/contracts/analyze",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert authed.status_code == 200
