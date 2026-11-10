"""Synchronous document loading: text extraction and the OCR decision.

`inspect_document` reads the PDF text layer or the DOCX body (paragraphs and
table cells, in document order) and decides whether OCR is needed. It never
calls a model; transcription happens in ocr.py with an injected OCR engine.

OCR is needed when:
* the upload is an image (.jpg, .jpeg, .png), or
* a PDF's text layer is missing or too thin to be a contract: the average number
  of non-whitespace characters per page is below `min_chars_per_page`
  (setting OCR_MIN_TEXT_CHARS_PER_PAGE, default 200). A typed contract page has
  well over a thousand characters; a scanned page has none, or only a stamp,
  header or page number that a scanner's OCR layer left behind.
"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader

IMAGE_MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
DEFAULT_MIN_CHARS_PER_PAGE = 200


class DocumentLoadError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass
class LoadedDocument:
    file_type: str  # "pdf" | "docx" | "image"
    text: str
    page_count: int = 1
    # None when the text layer is usable; else "image_upload" or "thin_text_layer".
    ocr_reason: str | None = None
    mime_type: str | None = None  # images only

    @property
    def needs_ocr(self) -> bool:
        return self.ocr_reason is not None


def detect_file_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in IMAGE_MIME_TYPES:
        return "image"
    raise DocumentLoadError(
        "unsupported_file_type", "Only .pdf, .docx, .jpg, .jpeg and .png files are supported."
    )


def normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _table_lines(table) -> list[str]:
    """One line per row, cells joined by " | "; merged cells are not repeated."""
    lines: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        seen: set[int] = set()
        for cell in row.cells:
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            parts = [paragraph.text for paragraph in cell.paragraphs]
            for nested in cell.tables:
                parts.extend(_table_lines(nested))
            text = " ".join(" ".join(parts).split())
            if text:
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def extract_docx_text(data: bytes) -> str:
    """Paragraphs and tables in document order (parties and prices often sit in tables)."""
    document = Document(BytesIO(data))
    lines: list[str] = []
    for block in document.iter_inner_content():
        if hasattr(block, "rows"):
            lines.extend(_table_lines(block))
        else:
            lines.append(block.text)
    return "\n".join(lines)


def extract_pdf_pages(data: bytes) -> list[str]:
    reader = PdfReader(BytesIO(data))
    return [page.extract_text() or "" for page in reader.pages]


def extract_pdf_text(data: bytes) -> str:
    return "\n".join(extract_pdf_pages(data))


def _dense_chars(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def is_thin_text_layer(pages: list[str], min_chars_per_page: int) -> bool:
    if not pages:
        return True
    return sum(_dense_chars(page) for page in pages) / len(pages) < min_chars_per_page


def inspect_document(
    file_name: str,
    data: bytes,
    min_chars_per_page: int = DEFAULT_MIN_CHARS_PER_PAGE,
) -> LoadedDocument:
    """Extract the text layer and decide whether OCR is needed (no model calls)."""
    file_type = detect_file_type(file_name)
    if file_type == "image":
        if not data:
            raise DocumentLoadError("unreadable_file", "Could not read the uploaded file.")
        mime_type = IMAGE_MIME_TYPES[Path(file_name).suffix.lower()]
        return LoadedDocument("image", "", 1, "image_upload", mime_type)
    try:
        if file_type == "pdf":
            pages = extract_pdf_pages(data)
            text = normalize_text("\n".join(pages))
            reason = "thin_text_layer" if is_thin_text_layer(pages, min_chars_per_page) else None
            return LoadedDocument("pdf", text, max(1, len(pages)), reason)
        text = normalize_text(extract_docx_text(data))
    except Exception as exc:
        raise DocumentLoadError("unreadable_file", "Could not read the uploaded file.") from exc
    if not text:
        raise DocumentLoadError("empty_text", "No readable text was found in the uploaded file.")
    return LoadedDocument("docx", text)


def load_contract_text(file_name: str, data: bytes) -> tuple[str, str]:
    """Text-layer-only loading (no OCR); kept for callers that cannot run OCR."""
    document = inspect_document(file_name, data, min_chars_per_page=1)
    if document.needs_ocr and not document.text:
        raise DocumentLoadError("empty_text", "No readable text was found in the uploaded file.")
    return document.file_type, document.text
