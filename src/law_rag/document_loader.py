from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


class DocumentLoadError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def detect_file_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    raise DocumentLoadError("unsupported_file_type", "Only .pdf and .docx files are supported.")


def normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_docx_text(data: bytes) -> str:
    document = Document(BytesIO(data))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def load_contract_text(file_name: str, data: bytes) -> tuple[str, str]:
    file_type = detect_file_type(file_name)

    try:
        raw_text = extract_pdf_text(data) if file_type == "pdf" else extract_docx_text(data)
    except Exception as exc:
        raise DocumentLoadError("unreadable_file", "Could not read the uploaded file.") from exc

    text = normalize_text(raw_text)
    if not text:
        raise DocumentLoadError("empty_text", "No readable text was found in the uploaded file.")

    return file_type, text
