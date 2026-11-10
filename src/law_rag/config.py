from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty: "TUFE_12M_AVERAGE_CHANGE_PERCENT=" (as in the README) means unset.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True, env_ignore_empty=True
    )

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

    # LLM call pacing (free-tier friendly): at most N calls in flight and a
    # minimum gap between call starts.
    llm_max_concurrency: int = Field(default=1, ge=1, validation_alias="LLM_MAX_CONCURRENCY")
    llm_min_interval_seconds: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="LLM_MIN_INTERVAL_SECONDS",
    )
    # Long contracts are processed in parts instead of being truncated.
    llm_clause_batch_chars: int = Field(default=6000, ge=500, validation_alias="LLM_CLAUSE_BATCH_CHARS")
    llm_max_findings_per_batch: int = Field(
        default=6,
        ge=1,
        validation_alias="LLM_MAX_FINDINGS_PER_BATCH",
    )
    llm_summary_chunk_chars: int = Field(default=6000, ge=500, validation_alias="LLM_SUMMARY_CHUNK_CHARS")

    # Corrective RAG loop.
    crag_use_llm_grader: bool = Field(default=True, validation_alias="CRAG_USE_LLM_GRADER")
    crag_max_rewrites: int = Field(default=2, ge=0, validation_alias="CRAG_MAX_REWRITES")
    crag_max_fetches_per_round: int = Field(
        default=6,
        ge=0,
        validation_alias="CRAG_MAX_FETCHES_PER_ROUND",
    )

    # Package 2 steps. Each LLM step costs about one call per clause batch
    # (missing clauses: one call); turn a step off to save free-tier quota.
    statutory_checks_enabled: bool = Field(default=True, validation_alias="STATUTORY_CHECKS_ENABLED")
    missing_clauses_enabled: bool = Field(default=True, validation_alias="MISSING_CLAUSES_ENABLED")
    clause_rewrites_enabled: bool = Field(default=True, validation_alias="CLAUSE_REWRITES_ENABLED")
    # Change in the 12-month average CPI (TÜFE on iki aylık ortalamalara göre
    # değişim, %) for the lease renewal cap (TBK m.344). It changes monthly and is
    # published by TÜİK; when unset, fixed-percentage increases are reported as
    # needs_review instead of being compared with a guessed value.
    tufe_12m_average_change_percent: float | None = Field(
        default=None,
        ge=0.0,
        validation_alias="TUFE_12M_AVERAGE_CHANGE_PERCENT",
    )


    # OCR for images and PDFs without a usable text layer (see document_loader.py).
    ocr_enabled: bool = Field(default=True, validation_alias="OCR_ENABLED")
    # Vision model for page transcription; empty means GEMINI_MODEL.
    ocr_model: str | None = Field(default=None, validation_alias="OCR_MODEL")
    ocr_max_pages: int = Field(default=10, ge=1, validation_alias="OCR_MAX_PAGES")
    ocr_min_text_chars_per_page: int = Field(
        default=200, ge=1, validation_alias="OCR_MIN_TEXT_CHARS_PER_PAGE"
    )
    ocr_render_dpi: int = Field(default=150, ge=50, le=400, validation_alias="OCR_RENDER_DPI")

    # Chat with an analysed contract (in-memory sessions, hybrid retrieval).
    embedding_model: str = Field(default="gemini-embedding-001", validation_alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=768, ge=128, le=3072, validation_alias="EMBEDDING_DIMENSIONS")
    embedding_batch_size: int = Field(default=100, ge=1, le=250, validation_alias="EMBEDDING_BATCH_SIZE")
    chat_session_ttl_seconds: int = Field(default=1800, ge=60, validation_alias="CHAT_SESSION_TTL_SECONDS")
    chat_max_sessions: int = Field(default=50, ge=1, validation_alias="CHAT_MAX_SESSIONS")
    chat_top_k: int = Field(default=6, ge=1, le=20, validation_alias="CHAT_TOP_K")
    chat_history_turns: int = Field(default=3, ge=0, le=10, validation_alias="CHAT_HISTORY_TURNS")
    chat_chunk_max_chars: int = Field(default=800, ge=200, validation_alias="CHAT_CHUNK_MAX_CHARS")
    # Minimum cosine similarity for a dense-only match; empty means the embedder's default.
    chat_min_dense_similarity: float | None = Field(
        default=None, ge=0.0, le=1.0, validation_alias="CHAT_MIN_DENSE_SIMILARITY"
    )


settings = Settings()
