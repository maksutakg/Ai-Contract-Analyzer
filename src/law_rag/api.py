from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from .call_gate import CallGate
from .chat_api import build_chat_router
from .config import Settings
from .document_loader import DocumentLoadError, inspect_document
from .export_docx import DOCX_MEDIA_TYPE, build_revised_contract_docx
from .graph import analyze_contract
from .llm import FakeContractAnalyzer, GeminiContractAnalyzer
from .models import ContractReport
from .ocr import FakeOcrEngine, GeminiOcrEngine, OcrEngine, transcribe_document
from .yargi_client import FakeYargiClient, RemoteYargiMcpClient


def _ocr_engine(app_settings: Settings, use_fake_clients: bool, gate: CallGate) -> OcrEngine | None:
    """Fake engine offline; Gemini with a key; None (-> ocr_unavailable) without a key."""
    if use_fake_clients:
        return FakeOcrEngine()
    if not app_settings.gemini_api_key:
        return None
    return GeminiOcrEngine(app_settings, gate)


def create_app(use_fake_clients: bool = False) -> FastAPI:
    app_settings = Settings()
    app = FastAPI(title="Law RAG MVP")
    chat_router, chat_store = build_chat_router(app_settings, use_fake_clients)
    app.include_router(chat_router)
    app.state.chat_store = chat_store

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/contracts/analyze", response_model=ContractReport)
    async def analyze_endpoint(
        file: UploadFile = File(...),
        contract_type: str | None = Form(default=None),
        party: str | None = Form(default=None),
    ):
        content = await file.read()
        if len(content) > app_settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "file_size_limit_exceeded",
                    "message": "Uploaded file exceeds the configured size limit.",
                },
            )

        offline = use_fake_clients or not app_settings.gemini_api_key
        # One gate per request paces OCR page calls and analysis calls together.
        gate = CallGate.from_settings(app_settings)
        ocr_result = None
        try:
            document = inspect_document(
                file.filename or "contract", content, app_settings.ocr_min_text_chars_per_page
            )
            text = document.text
            if document.needs_ocr:
                engine = _ocr_engine(app_settings, use_fake_clients, gate)
                ocr_result = await transcribe_document(document, content, engine, app_settings)
                text = ocr_result.text
        except DocumentLoadError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

        analyzer = FakeContractAnalyzer() if offline else GeminiContractAnalyzer(app_settings, gate)
        yargi_client = (
            RemoteYargiMcpClient(app_settings)
            if app_settings.use_remote_yargi and not use_fake_clients
            else FakeYargiClient()
        )

        try:
            return await analyze_contract(
                file_name=file.filename or "contract",
                file_type=document.file_type,
                raw_text=text,
                contract_type=contract_type,
                party=party,
                analyzer=analyzer,
                yargi_client=yargi_client,
                app_settings=app_settings,
                ocr=ocr_result.info if ocr_result else None,
                initial_limitations=ocr_result.limitations if ocr_result else None,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "analysis_failed",
                    "message": str(exc) or exc.__class__.__name__,
                },
            ) from exc
        finally:
            close = getattr(yargi_client, "aclose", None)
            if close is not None:
                await close()

    @app.post(
        "/api/v1/contracts/export-docx",
        response_class=Response,
        responses={200: {"content": {DOCX_MEDIA_TYPE: {}}}},
    )
    async def export_docx_endpoint(request: Request) -> Response:
        """Revised contract as .docx from a ContractReport JSON body. Nothing is stored."""
        body = await request.body()
        if len(body) > app_settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "report_size_limit_exceeded",
                    "message": "Report JSON exceeds the configured size limit.",
                },
            )
        try:
            report = ContractReport.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_report", "message": str(exc.errors(include_url=False)[:5])},
            ) from exc
        if not report.clauses:
            raise HTTPException(
                status_code=400,
                detail={"code": "no_clauses", "message": "The report has no clauses to export."},
            )
        content = build_revised_contract_docx(report)
        return Response(
            content=content,
            media_type=DOCX_MEDIA_TYPE,
            headers={"Content-Disposition": 'attachment; filename="revize-sozlesme.docx"'},
        )

    return app


app = create_app()
