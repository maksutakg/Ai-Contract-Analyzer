from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from .auth import AuthError, AuthStore
from .config import Settings
from .document_loader import DocumentLoadError, load_contract_text
from .graph import analyze_contract
from .llm import FakeContractAnalyzer, GeminiContractAnalyzer
from .models import (
    AuthCredentialsRequest,
    AuthSessionResponse,
    ContractReport,
    ContractType,
    UserResponse,
)
from .yargi_client import FakeYargiClient, RemoteYargiMcpClient


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(
    use_fake_clients: bool = False,
    frontend_dist: Path = FRONTEND_DIST,
    auth_db_path: Path | None = None,
) -> FastAPI:
    app_settings = Settings()
    auth_store = AuthStore(
        db_path=auth_db_path or app_settings.auth_db_path,
        secret_key=app_settings.auth_secret_key,
        token_ttl_seconds=app_settings.auth_token_ttl_seconds,
    )
    app = FastAPI(title="Law RAG MVP")

    def require_current_user(authorization: str | None = Header(default=None)) -> UserResponse:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "authentication_required",
                    "message": "Authentication is required. Please sign in.",
                },
            )
        token = authorization[7:].strip()
        try:
            return auth_store.verify_token(token)
        except AuthError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/auth/register", status_code=201, response_model=AuthSessionResponse)
    async def register_endpoint(payload: AuthCredentialsRequest) -> AuthSessionResponse:
        try:
            return auth_store.register_user(payload.email, payload.password)
        except AuthError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.post("/api/v1/auth/login", response_model=AuthSessionResponse)
    async def login_endpoint(payload: AuthCredentialsRequest) -> AuthSessionResponse:
        try:
            return auth_store.authenticate_user(payload.email, payload.password)
        except AuthError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.get("/api/v1/auth/me", response_model=UserResponse)
    async def me_endpoint(current_user: UserResponse = Depends(require_current_user)) -> UserResponse:
        return current_user

    @app.post("/api/v1/contracts/analyze", response_model=ContractReport)
    async def analyze_endpoint(
        file: UploadFile = File(...),
        # Not "ContractType | None": that becomes anyOf, which Swagger renders as a free-text box prefilled with "string".
        contract_type: ContractType = Form(default=None),
        _current_user: UserResponse = Depends(require_current_user),
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
            report = await analyze_contract(
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

        # Say which backends actually ran, so a missing key or disabled MCP is visible in the report.
        if isinstance(analyzer, GeminiContractAnalyzer):
            report.llm_engine = app_settings.gemini_model
        elif not app_settings.gemini_api_key:
            report.llm_engine = "rules (GEMINI_API_KEY is not set)"
        if isinstance(yargi_client, RemoteYargiMcpClient):
            report.yargi_source = app_settings.yargi_mcp_url
        elif not app_settings.use_remote_yargi:
            report.yargi_source = "fake (USE_REMOTE_YARGI is false)"
        return report

    # Mounted last so API routes win; serves the built UI from the same origin (no CORS).
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()
