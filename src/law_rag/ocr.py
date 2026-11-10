"""OCR for scanned PDFs and photographed contracts.

document_loader.py decides whether OCR is needed; this module renders page
images and transcribes them with an injected engine behind the `OcrEngine`
protocol (the same pattern as the analyzer):

* GeminiOcrEngine sends each page image to the configured Gemini-API model
  (OCR_MODEL, default GEMINI_MODEL; Gemma 3 accepts image input) with a prompt
  asking for a verbatim transcription. Pages are processed one by one through
  the request's call gate.
* FakeOcrEngine is deterministic and offline (tests, `use_fake_clients=True`).

PDF pages are rendered with pypdfium2 (no system install) in grayscale and
encoded as PNG with the standard library, so Pillow is not needed.
"""

import struct
import zlib
from dataclasses import dataclass
from typing import Any, Protocol

from .call_gate import CallGate
from .document_loader import DocumentLoadError, LoadedDocument, normalize_text
from .models import OcrInfo

OCR_USED_LIMITATION = (
    "The contract text was transcribed from page images by OCR ({pages} page(s)); the "
    "transcription may contain errors, so check amounts, dates and names against the original."
)
OCR_PROVIDER_LIMITATION = (
    "Page images of the contract were sent to the model provider (Gemini API) for transcription."
)
OCR_FAILED_PAGES_LIMITATION = (
    "OCR failed for page(s) {pages}; their text is missing from the analysis."
)
FAILED_PAGE_PLACEHOLDER = "[Sayfa {page} okunamadı]"
_BLANK_MARKER = "[BOŞ SAYFA]"

OCR_PROMPT = (
    "Transcribe the text of this scanned Turkish contract page exactly as written. "
    "Keep the original language and Turkish characters (ç, ğ, ı, İ, ö, ş, ü), clause numbering "
    "(MADDE 1, 1., 1.1 ...), headings and line breaks. Render tables row by row with cells "
    "separated by ' | '. Do not translate, summarise, correct, explain or add anything; do not "
    "use markdown. Write [okunamıyor] for a word you cannot read. If the page has no text, "
    f"reply only {_BLANK_MARKER}."
)


@dataclass(frozen=True)
class PageImage:
    number: int  # 1-based
    data: bytes
    mime_type: str


class OcrEngine(Protocol):
    kind: str  # "gemini" | "fake"
    model: str | None

    async def transcribe_page(self, page: PageImage) -> str:
        """Verbatim text of one page image."""
        ...


class FakeOcrEngine:
    """Deterministic offline engine.

    If the image bytes contain the marker b"FAKE-OCR-TEXT:", the UTF-8 text after
    it is the page text (lets tests and smoke checks control the transcription);
    otherwise a fixed sample lease page is returned.
    """

    kind = "fake"
    model: str | None = None
    MARKER = b"FAKE-OCR-TEXT:"
    SAMPLE_TEXT = (
        "KONUT KİRA SÖZLEŞMESİ\n"
        "Kiraya veren: Örnek Kiraya Veren, Kiracı: Örnek Kiracı\n"
        "MADDE 1 - KİRALANAN\nKiralanan, Kadıköy/İstanbul adresindeki konuttur.\n"
        "MADDE 2 - KİRA BEDELİ\nAylık kira bedeli 20.000 TL olup her ayın 5'inde ödenir.\n"
        "MADDE 3 - DEPOZİTO\nKiracı 100.000 TL depozito öder.\n"
        "MADDE 4 - YETKİ\nUyuşmazlıklarda Ankara Mahkemeleri yetkilidir."
    )

    async def transcribe_page(self, page: PageImage) -> str:
        position = page.data.find(self.MARKER)
        if position >= 0:
            return page.data[position + len(self.MARKER) :].decode("utf-8", errors="replace")
        return self.SAMPLE_TEXT


class GeminiOcrEngine:
    kind = "gemini"

    def __init__(self, app_settings: Any, gate: CallGate | None = None) -> None:
        from google import genai  # imported here so the fake path never needs it

        if not app_settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiOcrEngine.")
        self.model = app_settings.ocr_model or app_settings.gemini_model
        self._client = genai.Client(api_key=app_settings.gemini_api_key)
        self._gate = gate or CallGate.from_settings(app_settings)

    async def transcribe_page(self, page: PageImage) -> str:
        from google.genai import types

        async def call() -> Any:
            return await self._client.aio.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=page.data, mime_type=page.mime_type), OCR_PROMPT],
            )

        response = await self._gate.run(call)
        return response.text or ""


def clean_transcription(text: str) -> str:
    """Drop markdown fences and the blank-page marker; keep the line structure."""
    lines = [line for line in (text or "").strip().splitlines() if not line.strip().startswith("```")]
    cleaned = "\n".join(lines).strip()
    return "" if cleaned == _BLANK_MARKER else cleaned


# ------------------------------------------------------------------ rendering
def _png(width: int, height: int, color_type: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _bitmap_to_png(bitmap: Any) -> bytes:
    width, height, stride, channels = bitmap.width, bitmap.height, bitmap.stride, bitmap.n_channels
    buffer = bytes(bitmap.buffer)
    rows = [buffer[y * stride : y * stride + width * channels] for y in range(height)]
    if channels == 1:
        return _png(width, height, 0, rows)
    # Rendered with rev_byteorder=True, so 3/4-channel rows are RGB / RGBx.
    if channels == 4:
        rows = [bytes(b for i, b in enumerate(row) if i % 4 != 3) for row in rows]
    return _png(width, height, 2, rows)


def render_pdf_pages(data: bytes, dpi: int) -> list[PageImage]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        pages: list[PageImage] = []
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=dpi / 72, grayscale=True, rev_byteorder=True)
            pages.append(PageImage(index + 1, _bitmap_to_png(bitmap), "image/png"))
            bitmap.close()
            page.close()
        return pages
    finally:
        document.close()


# --------------------------------------------------------------- orchestration
@dataclass
class OcrResult:
    text: str
    info: OcrInfo
    limitations: list[str]


async def transcribe_document(
    document: LoadedDocument,
    data: bytes,
    engine: OcrEngine | None,
    app_settings: Any,
) -> OcrResult:
    """Transcribe a document that needs OCR; raises DocumentLoadError with a specific code."""
    if not getattr(app_settings, "ocr_enabled", True):
        raise DocumentLoadError(
            "ocr_disabled",
            "The file has no usable text layer and OCR is disabled (OCR_ENABLED=false).",
            422,
        )
    if engine is None:
        raise DocumentLoadError(
            "ocr_unavailable",
            "The file has no usable text layer and OCR needs a configured GEMINI_API_KEY.",
            503,
        )
    max_pages = getattr(app_settings, "ocr_max_pages", 10)
    if document.page_count > max_pages:
        raise DocumentLoadError(
            "ocr_page_limit_exceeded",
            f"The file needs OCR for {document.page_count} pages; the limit is {max_pages} (OCR_MAX_PAGES).",
            413,
        )
    try:
        if document.file_type == "image":
            pages = [PageImage(1, data, document.mime_type or "image/png")]
        else:
            pages = render_pdf_pages(data, getattr(app_settings, "ocr_render_dpi", 150))
    except Exception as exc:
        raise DocumentLoadError("unreadable_file", "Could not render the file's pages for OCR.") from exc

    texts: list[str] = []
    failed: list[int] = []
    for page in pages:  # sequential: one model call at a time through the gate
        try:
            texts.append(clean_transcription(await engine.transcribe_page(page)))
        except Exception:
            failed.append(page.number)
            texts.append(FAILED_PAGE_PLACEHOLDER.format(page=page.number))
    if len(failed) == len(pages):
        raise DocumentLoadError("ocr_failed", "OCR failed for every page of the file.", 502)
    text = normalize_text("\n".join(texts))
    if not text or all(not t or t.startswith("[Sayfa ") for t in texts):
        raise DocumentLoadError("empty_text", "No readable text was found in the uploaded file.")

    limitations = [OCR_USED_LIMITATION.format(pages=len(pages))]
    if engine.kind == "gemini":
        limitations.append(OCR_PROVIDER_LIMITATION)
    if failed:
        limitations.append(OCR_FAILED_PAGES_LIMITATION.format(pages=", ".join(map(str, failed))))
    info = OcrInfo(
        reason=document.ocr_reason or "image_upload",  # type: ignore[arg-type]
        pages=len(pages),
        failed_pages=failed,
        engine=engine.kind,  # type: ignore[arg-type]
        model=engine.model,
    )
    return OcrResult(text=text, info=info, limitations=limitations)
