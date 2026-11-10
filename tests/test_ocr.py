from io import BytesIO

import httpx
import pytest
from docx import Document
from pypdf import PdfWriter

from law_rag.api import create_app
from law_rag.config import Settings
from law_rag.document_loader import DocumentLoadError, LoadedDocument, inspect_document
from law_rag.ocr import (
    OCR_FAILED_PAGES_LIMITATION,
    OCR_PROVIDER_LIMITATION,
    OCR_USED_LIMITATION,
    FakeOcrEngine,
    OcrEngine,
    PageImage,
    transcribe_document,
)


def _zero_page_pdf() -> bytes:
    writer = PdfWriter()
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _blank_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


class BlankSecondPageOcrEngine:
    kind = "fake"
    model = None

    async def transcribe_page(self, page: PageImage) -> str:
        if page.number == 1:
            raise RuntimeError("page 1 error")
        return "[BOŞ SAYFA]"


class PartialFailGeminiLikeEngine:
    kind = "gemini"
    model = "gemma-3-27b-it"

    async def transcribe_page(self, page: PageImage) -> str:
        if page.number == 2:
            raise RuntimeError("timeout")
        return "MADDE 1 - KONU\nKiralanan konuttur."


class AlwaysFailEngine:
    kind = "fake"
    model = None

    async def transcribe_page(self, page: PageImage) -> str:
        raise RuntimeError("boom")


class SingleBlankEngine:
    kind = "fake"
    model = None

    async def transcribe_page(self, page: PageImage) -> str:
        return "```\n[BOŞ SAYFA]\n```"


@pytest.mark.asyncio
async def test_zero_page_pdf_raises_empty_text() -> None:
    with pytest.raises(DocumentLoadError) as exc_info:
        inspect_document("empty.pdf", _zero_page_pdf())

    assert exc_info.value.code == "empty_text"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_failed_page_plus_blank_page_raises_ocr_failed(monkeypatch) -> None:
    loaded = LoadedDocument(file_type="pdf", text="", page_count=2, ocr_reason="thin_text_layer")
    monkeypatch.setattr(
        "law_rag.ocr.render_pdf_pages",
        lambda data, dpi: [
            PageImage(1, b"p1", "image/png"),
            PageImage(2, b"p2", "image/png"),
        ],
    )
    engine: OcrEngine = BlankSecondPageOcrEngine()

    with pytest.raises(DocumentLoadError) as exc_info:
        await transcribe_document(loaded, b"pdf", engine, Settings(gemini_api_key="x"))

    assert exc_info.value.code == "ocr_failed"
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_ocr_error_codes_disabled_unavailable_page_limit_all_fail_and_blank(monkeypatch) -> None:
    loaded = LoadedDocument(file_type="image", text="", page_count=1, ocr_reason="image_upload", mime_type="image/png")

    with pytest.raises(DocumentLoadError) as disabled:
        await transcribe_document(loaded, b"png", FakeOcrEngine(), Settings(ocr_enabled=False))
    assert disabled.value.code == "ocr_disabled"
    assert disabled.value.status_code == 422

    with pytest.raises(DocumentLoadError) as unavailable:
        await transcribe_document(loaded, b"png", None, Settings(ocr_enabled=True))
    assert unavailable.value.code == "ocr_unavailable"
    assert unavailable.value.status_code == 503

    many_pages = LoadedDocument(file_type="pdf", text="", page_count=11, ocr_reason="thin_text_layer")
    with pytest.raises(DocumentLoadError) as limited:
        await transcribe_document(many_pages, b"pdf", FakeOcrEngine(), Settings(ocr_max_pages=10))
    assert limited.value.code == "ocr_page_limit_exceeded"
    assert limited.value.status_code == 413

    with pytest.raises(DocumentLoadError) as all_failed:
        await transcribe_document(loaded, b"png", AlwaysFailEngine(), Settings())
    assert all_failed.value.code == "ocr_failed"
    assert all_failed.value.status_code == 502

    with pytest.raises(DocumentLoadError) as blank_only:
        await transcribe_document(loaded, b"png", SingleBlankEngine(), Settings())
    assert blank_only.value.code == "empty_text"
    assert blank_only.value.status_code == 400


@pytest.mark.asyncio
async def test_ocr_partial_page_failure_keeps_placeholder_and_limitations(monkeypatch) -> None:
    loaded = LoadedDocument(file_type="pdf", text="", page_count=2, ocr_reason="thin_text_layer")
    monkeypatch.setattr(
        "law_rag.ocr.render_pdf_pages",
        lambda data, dpi: [
            PageImage(1, b"p1", "image/png"),
            PageImage(2, b"p2", "image/png"),
        ],
    )
    result = await transcribe_document(loaded, b"pdf", PartialFailGeminiLikeEngine(), Settings())

    assert "MADDE 1 - KONU" in result.text
    assert "[Sayfa 2 okunamadı]" in result.text
    assert result.info.failed_pages == [2]
    assert result.info.engine == "gemini"
    assert result.info.model == "gemma-3-27b-it"
    assert OCR_USED_LIMITATION.format(pages=2) in result.limitations
    assert OCR_PROVIDER_LIMITATION in result.limitations
    assert OCR_FAILED_PAGES_LIMITATION.format(pages="2") in result.limitations


@pytest.mark.asyncio
async def test_document_loader_docx_tables_unsupported_type_and_thin_pdf_rendering() -> None:
    with pytest.raises(DocumentLoadError) as unsupported:
        inspect_document("contract.txt", b"hello")
    assert unsupported.value.code == "unsupported_file_type"
    assert unsupported.value.status_code == 400

    doc = Document()
    doc.add_paragraph("KİRA SÖZLEŞMESİ")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Aylık Kira"
    table.rows[0].cells[1].text = "25.000 TL"
    buf = BytesIO()
    doc.save(buf)
    loaded_docx = inspect_document("contract.docx", buf.getvalue())
    assert loaded_docx.needs_ocr is False
    assert "Aylık Kira | 25.000 TL" in loaded_docx.text

    pdf_bytes = _blank_pdf(1)
    loaded_pdf = inspect_document("scan.pdf", pdf_bytes)
    assert loaded_pdf.needs_ocr is True
    assert loaded_pdf.ocr_reason == "thin_text_layer"

    ocr_result = await transcribe_document(loaded_pdf, pdf_bytes, FakeOcrEngine(), Settings(ocr_render_dpi=72))
    assert ocr_result.info.pages == 1
    assert ocr_result.info.reason == "thin_text_layer"
    assert "MADDE 3 - DEPOZİTO" in ocr_result.text


@pytest.mark.asyncio
async def test_api_ocr_error_http_statuses(monkeypatch) -> None:
    monkeypatch.setenv("OCR_ENABLED", "false")
    app_disabled = create_app(use_fake_clients=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_disabled), base_url="http://testserver"
    ) as client:
        res_disabled = await client.post(
            "/api/v1/contracts/analyze",
            files={"file": ("scan.png", b"\x89PNG\r\n\x1a\nabc", "image/png")},
        )
        assert res_disabled.status_code == 422
        assert res_disabled.json()["detail"]["code"] == "ocr_disabled"

        res_unsupported = await client.post(
            "/api/v1/contracts/analyze",
            files={"file": ("notes.txt", b"plain text", "text/plain")},
        )
        assert res_unsupported.status_code == 400
        assert res_unsupported.json()["detail"]["code"] == "unsupported_file_type"

    monkeypatch.setenv("OCR_ENABLED", "true")
    monkeypatch.setenv("OCR_MAX_PAGES", "1")
    app_limited = create_app(use_fake_clients=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_limited), base_url="http://testserver"
    ) as client:
        res_limit = await client.post(
            "/api/v1/contracts/analyze",
            files={"file": ("two.pdf", _blank_pdf(2), "application/pdf")},
        )
        assert res_limit.status_code == 413
        assert res_limit.json()["detail"]["code"] == "ocr_page_limit_exceeded"

    monkeypatch.setattr(
        "law_rag.api.Settings",
        lambda: Settings(_env_file=None, gemini_api_key=None, ocr_enabled=True, ocr_max_pages=10),
    )
    app_no_key = create_app(use_fake_clients=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_no_key), base_url="http://testserver"
    ) as client:
        res_unavail = await client.post(
            "/api/v1/contracts/analyze",
            files={"file": ("scan.png", b"\x89PNG\r\n\x1a\nabc", "image/png")},
        )
        assert res_unavail.status_code == 503
        assert res_unavail.json()["detail"]["code"] == "ocr_unavailable"
