"""Chat endpoints: create a session from a report, ask questions, delete it.

POST   /api/v1/chat/sessions                 body: ContractReport JSON -> 201 ChatSessionCreated
POST   /api/v1/chat/sessions/{id}/messages   body: {"question": "..."}  -> ChatAnswer
DELETE /api/v1/chat/sessions/{id}                                         -> 204

Unknown or expired session ids give 404 `chat_session_not_found`; more than
CHAT_MAX_SESSIONS live sessions give 429 `chat_session_limit`.
"""

from collections import Counter

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import ValidationError

from .call_gate import CallGate
from .chat_answer import (
    DISCLAIMER,
    NOTE_LEXICAL_ONLY,
    ChatAnswerer,
    FakeChatAnswerer,
    GeminiChatAnswerer,
    Turn,
    snippet,
)
from .chat_index import build_index, retrieve
from .chat_models import ChatAnswer, ChatCitation, ChatQuestion, ChatSessionCreated
from .chat_sessions import ChatSessionStore, SessionLimitReached, SessionNotFound
from .config import Settings
from .embeddings import Embedder, FakeEmbedder, GeminiEmbedder
from .models import ContractReport


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def build_chat_router(app_settings: Settings, use_fake_clients: bool) -> tuple[APIRouter, ChatSessionStore]:
    """The router and its session store (exposed as app.state.chat_store for tests)."""
    router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
    store = ChatSessionStore(
        app_settings.chat_session_ttl_seconds,
        app_settings.chat_max_sessions,
        app_settings.chat_history_turns,
    )
    offline = use_fake_clients or not app_settings.gemini_api_key
    gate = CallGate.from_settings(app_settings)  # shared by all chat sessions
    embedder: Embedder = FakeEmbedder() if offline else GeminiEmbedder(app_settings, gate)
    answerer: ChatAnswerer = FakeChatAnswerer() if offline else GeminiChatAnswerer(app_settings, gate)

    def session_or_404(session_id: str):
        try:
            return store.get(session_id)
        except SessionNotFound as exc:
            raise _error(
                404, "chat_session_not_found", "Chat session not found or expired; create a new session."
            ) from exc

    @router.post("/sessions", status_code=201, response_model=ChatSessionCreated)
    async def create_session(request: Request) -> ChatSessionCreated:
        body = await request.body()
        if len(body) > app_settings.max_upload_bytes:
            raise _error(413, "report_size_limit_exceeded", "Report JSON exceeds the configured size limit.")
        try:
            report = ContractReport.model_validate_json(body)
        except ValidationError as exc:
            raise _error(422, "invalid_report", str(exc.errors(include_url=False)[:5])) from exc
        if not report.clauses:
            raise _error(400, "no_clauses", "The report has no clauses to chat about.")
        try:
            store.ensure_capacity()
        except SessionLimitReached as exc:
            raise _error(429, "chat_session_limit", "Too many active chat sessions; try again later.") from exc
        index = await build_index(report, embedder, app_settings.chat_chunk_max_chars)
        try:
            session = store.create(index)
        except SessionLimitReached as exc:
            raise _error(429, "chat_session_limit", "Too many active chat sessions; try again later.") from exc
        return ChatSessionCreated(
            session_id=session.id,
            expires_at=session.expires_at_iso(),
            ttl_seconds=store.ttl_seconds,
            chunk_count=len(index.chunks),
            chunk_types=dict(Counter(chunk.type for chunk in index.chunks)),
            retrieval_mode="hybrid" if index.dense_available else "lexical",
            embedding_model=index.embedder_name,
            notes=[] if index.dense_available else [NOTE_LEXICAL_ONLY],
            disclaimer=DISCLAIMER,
        )

    @router.post("/sessions/{session_id}/messages", response_model=ChatAnswer)
    async def ask(session_id: str, body: ChatQuestion) -> ChatAnswer:
        session = session_or_404(session_id)
        question = " ".join(body.question.split())
        if not question:
            raise _error(422, "empty_question", "The question is empty.")
        async with session.lock:
            store.touch(session)
            result = await retrieve(
                session.index,
                question,
                embedder,
                mode="hybrid",
                top_k=app_settings.chat_top_k,
                min_dense_similarity=app_settings.chat_min_dense_similarity,
            )
            chunks = [item.chunk for item in result.chunks]
            draft = await answerer.answer(question, session.recent_history(), chunks)
            store.record(session, Turn(question, draft.text))
            store.touch(session)
        by_id = {chunk.id: chunk for chunk in chunks}
        citations = [
            ChatCitation(
                id=chunk.id,
                type=chunk.type,
                clause_id=chunk.clause_id,
                title=chunk.title,
                snippet=snippet(chunk.text),
            )
            for chunk in (by_id[item] for item in draft.cited_ids if item in by_id)
        ]
        notes = ([NOTE_LEXICAL_ONLY] if result.dense_failed else []) + draft.notes
        return ChatAnswer(
            session_id=session.id,
            question=question,
            answer=draft.text,
            covered=draft.covered,
            answered_by=draft.answered_by,  # type: ignore[arg-type]
            citations=citations,
            retrieval_mode=result.mode,
            notes=notes,
            disclaimer=DISCLAIMER,
            expires_at=session.expires_at_iso(),
        )

    @router.delete("/sessions/{session_id}", status_code=204, response_class=Response)
    async def delete_session(session_id: str) -> Response:
        if not store.delete(session_id):
            raise _error(404, "chat_session_not_found", "Chat session not found or expired.")
        return Response(status_code=204)

    return router, store
