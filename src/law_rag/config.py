from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemma-3-27b-it", validation_alias="GEMINI_MODEL")
    yargi_mcp_url: str = Field(
        default="https://yargimcp.surucu.dev/mcp/",
        validation_alias="YARGI_MCP_URL",
    )
    use_remote_yargi: bool = Field(default=False, validation_alias="USE_REMOTE_YARGI")
    yargi_max_results_per_finding: int = Field(
        default=3,
        validation_alias="YARGI_MAX_RESULTS_PER_FINDING",
    )
    yargi_max_total_decisions: int = Field(default=10, validation_alias="YARGI_MAX_TOTAL_DECISIONS")
    yargi_fetch_documents: bool = Field(default=False, validation_alias="YARGI_FETCH_DOCUMENTS")
    yargi_request_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="YARGI_REQUEST_TIMEOUT_SECONDS",
    )
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, validation_alias="MAX_UPLOAD_BYTES")


settings = Settings()
