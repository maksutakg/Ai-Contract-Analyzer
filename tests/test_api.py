from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from law_rag.api import create_app


def docx_bytes(*lines: str) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def post_contract(data: dict[str, str]):
    client = TestClient(create_app(use_fake_clients=True))
    return client.post(
        "/api/v1/contracts/analyze",
        files={"file": ("c.docx", docx_bytes("MADDE 1 - FESIH", "Taraflar derhal fesih hakkina sahiptir."))},
        data=data,
    )


def test_contract_type_is_optional_and_report_names_backends() -> None:
    response = post_contract({})

    assert response.status_code == 200
    assert response.json()["llm_engine"].startswith("rules")
    assert response.json()["yargi_source"].startswith("fake")


def test_contract_type_rejects_values_outside_the_list() -> None:
    assert post_contract({"contract_type": "string"}).status_code == 422
    assert post_contract({"contract_type": "lease"}).status_code == 200
