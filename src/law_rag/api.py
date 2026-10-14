from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .config import Settings
from .document_loader import DocumentLoadError, load_contract_text
from .graph import analyze_contract
from .llm import FakeContractAnalyzer, GeminiContractAnalyzer
from .models import ContractReport
from .yargi_client import FakeYargiClient, RemoteYargiMcpClient


def create_app(use_fake_clients: bool = False) -> FastAPI:
    app_settings = Settings()
    app = FastAPI(title="Law RAG MVP")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/contracts/analyze", response_model=ContractReport)
    async def analyze_endpoint(
        file: UploadFile = File(...),
        contract_type: str | None = Form(default=None),
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

        try:
            file_type, text = load_contract_text(file.filename or "contract", content)
        except DocumentLoadError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

        analyzer = (
            FakeContractAnalyzer()
            if use_fake_clients or not app_settings.gemini_api_key
            else GeminiContractAnalyzer(app_settings)
        )
        yargi_client = (
            RemoteYargiMcpClient(app_settings)
            if app_settings.use_remote_yargi and not use_fake_clients
            else FakeYargiClient()
        )

        try:
            return await analyze_contract(
                file_name=file.filename or "contract",
                file_type=file_type,
                raw_text=text,
                contract_type=contract_type,
                analyzer=analyzer,
                yargi_client=yargi_client,
                app_settings=app_settings,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "analysis_failed",
                    "message": str(exc) or exc.__class__.__name__,
                },
            ) from exc

    return app


app = create_app()
