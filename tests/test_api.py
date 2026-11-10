from io import BytesIO

import httpx
import pytest
from docx import Document

from law_rag.api import create_app
from law_rag.export_docx import DOCX_MEDIA_TYPE
from law_rag.models import ContractReport
from law_rag.ocr import FakeOcrEngine


def _docx_bytes(paragraphs: list[str]) -> bytes:
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_health_and_analyze_docx_returns_all_package2_fields() -> None:
    app = create_app(use_fake_clients=True)
    payload = _docx_bytes(
        [
            "KONUT KİRA SÖZLEŞMESİ",
            "MADDE 1 - KONU",
            "Kadıköy/İstanbul adresindeki daire konut olarak kiraya verilmiştir.",
            "MADDE 2 - KİRA BEDELİ",
            "Aylık kira bedeli 20.000 TL olup banka yoluyla ödenir.",
            "MADDE 3 - DEPOZİTO",
            "Kiracı 100.000 TL depozito öder; depozito iade edilmez.",
            "MADDE 4 - YETKİ",
            "Uyuşmazlıklarda Ankara mahkemeleri yetkilidir.",
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        response = await client.post(
            "/api/v1/contracts/analyze",
            data={"contract_type": "kira", "party": "kiracı"},
            files={
                "file": (
                    "kira.docx",
                    payload,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert response.status_code == 200
        report = ContractReport.model_validate(response.json())

        assert report.contract_type == "lease"
        assert report.party == "tenant"
        assert report.ocr is None
        assert len(report.statutory_checks) == 4
        assert any(check.status == "violation" for check in report.statutory_checks)
        assert len(report.missing_clauses) > 0
        assert len(report.rewrites) > 0
        assert len(report.retrieval_trace) > 0
        assert any(finding.legal_references for finding in report.findings)
        assert any(finding.applies_to_user for finding in report.findings)

        export_res = await client.post(
            "/api/v1/contracts/export-docx",
            content=response.content,
            headers={"Content-Type": "application/json"},
        )
        assert export_res.status_code == 200
        assert export_res.headers["content-type"].startswith(DOCX_MEDIA_TYPE)
        exported_doc = Document(BytesIO(export_res.content))
        all_text = "\n".join(p.text for p in exported_doc.paragraphs)
        assert "[DEĞİŞTİRİLDİ" in all_text
        assert len(exported_doc.tables) == 1


@pytest.mark.asyncio
async def test_analyze_image_runs_ocr_and_export_errors() -> None:
    app = create_app(use_fake_clients=True)
    image_bytes = b"\x89PNG\r\n\x1a\n" + FakeOcrEngine.MARKER + (
        "KONUT KİRA SÖZLEŞMESİ\n"
        "MADDE 1 - DEPOZİTO\n"
        "Kiracı 100.000 TL depozito öder; depozito iade edilmez."
    ).encode("utf-8")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        ocr_res = await client.post(
            "/api/v1/contracts/analyze",
            files={"file": ("scan.png", image_bytes, "image/png")},
        )
        assert ocr_res.status_code == 200
        ocr_report = ContractReport.model_validate(ocr_res.json())
        assert ocr_report.ocr is not None
        assert ocr_report.ocr.reason == "image_upload"
        assert ocr_report.ocr.engine == "fake"
        assert ocr_report.ocr.pages == 1

        bad_export = await client.post("/api/v1/contracts/export-docx", content="{}")
        assert bad_export.status_code == 422
        assert bad_export.json()["detail"]["code"] == "invalid_report"

        empty_report = ocr_report.model_copy(update={"clauses": []}).model_dump_json()
        no_clauses = await client.post("/api/v1/contracts/export-docx", content=empty_report)
        assert no_clauses.status_code == 400
        assert no_clauses.json()["detail"]["code"] == "no_clauses"

