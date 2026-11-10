from io import BytesIO

import httpx
import pytest
from docx import Document

from law_rag.api import create_app
from law_rag.chat_answer import (
    DISCLAIMER,
    NOTE_EXTRACTIVE_FALLBACK,
    NOTE_STATUTE_STRIPPED,
    GeminiChatAnswerer,
    Turn,
)
from law_rag.chat_index import Chunk, build_chunks, build_index, retrieve
from law_rag.chat_sessions import ChatSessionStore, SessionLimitReached, SessionNotFound
from law_rag.config import Settings
from law_rag.embeddings import FakeEmbedder
from law_rag.models import (
    Clause,
    ClauseRewrite,
    ContractReport,
    LegalReference,
    MissingClause,
    RiskFinding,
    StatutoryCheck,
    YargiDecision,
)


def _sample_report() -> ContractReport:
    ref = LegalReference(
        law_name="Türk Borçlar Kanunu",
        law_number="6098",
        article="m.342",
        summary="Güvence üç aylık kira bedelini aşamaz.",
        url="https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6098",
    )
    return ContractReport(
        contract_summary="Konut kira sözleşmesi özeti.",
        risk_score=45,
        risk_level="medium",
        contract_type="lease",
        party="tenant",
        clauses=[
            Clause(
                id="clause-1",
                title="MADDE 1 - KONU",
                text="Kiralanan, Kadıköy adresindeki konuttur.",
            ),
            Clause(
                id="clause-2",
                title="MADDE 2 - DEPOZİTO",
                text="Kiracı beş aylık kira tutarında 100.000 TL depozito öder. " + ("Ek şart. " * 40),
            ),
        ],
        findings=[
            RiskFinding(
                id="finding-1",
                category="deposit_forfeiture",
                severity="high",
                explanation="Güvence bedeli yasal sınırı aşıyor.",
                recommendation="Üç aylık kira sınırına indirin.",
                clause_id="clause-2",
                legal_references=[ref],
            )
        ],
        statutory_checks=[
            StatutoryCheck(
                rule_id="lease_deposit_cap",
                title="Güvence bedeli üst sınırı",
                status="violation",
                clause_id="clause-2",
                extracted_value="100.000 TL (5 aylık kira)",
                limit="En fazla 3 aylık kira bedeli",
                explanation="Depozito üç aylık kirayı aşamaz.",
                legal_basis=ref,
                finding_id="finding-1",
                extracted_by="rule_based",
            )
        ],
        missing_clauses=[
            MissingClause(
                topic="handover",
                title="Teslim ve tahliyede durum tespiti",
                importance="medium",
                explanation="Teslim tutanağı eksiktir.",
                suggested_clause="Kiralanan tutanakla teslim edilir.",
                detected_by="rule_based",
            )
        ],
        rewrites=[
            ClauseRewrite(
                clause_id="clause-2",
                finding_ids=["finding-1"],
                original_text="Kiracı beş aylık kira tutarında 100.000 TL depozito öder.",
                suggested_text="Kiracı en fazla üç aylık kira bedeli tutarında depozito öder.",
                rationale="Üst sınır üç aydır.",
                generated_by="rule_based",
            )
        ],
        related_decisions=[
            YargiDecision(
                finding_id="finding-1",
                finding_category="deposit_forfeiture",
                source="Bedesten",
                title="Yargıtay Depozito Kararı",
                relevance="Depozito iadesi",
                excerpt="Depozito üç aylık kirayı aşamaz.",
                grade="relevant",
            )
        ],
    )


class FailingEmbedder(FakeEmbedder):
    async def embed_query(self, text: str):
        raise RuntimeError("embedding down")


class FakeAnswerCapture:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def generate_content(self, *, model: str, contents: str):
        self.prompts.append(contents)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

        class Response:
            text = reply

        return Response()


def _build_gemini_answerer(monkeypatch, replies: list[str]) -> tuple[GeminiChatAnswerer, FakeAnswerCapture]:
    capture = FakeAnswerCapture(replies)
    client = type("Client", (), {"aio": type("Aio", (), {"models": capture})()})()
    monkeypatch.setattr("google.genai.Client", lambda api_key: client)
    answerer = GeminiChatAnswerer(Settings(gemini_api_key="test"))
    return answerer, capture


def test_build_chunks_covers_all_report_sections_and_splits_long_clauses() -> None:
    chunks = build_chunks(_sample_report(), max_chars=120)
    ids = [chunk.id for chunk in chunks]
    types = {chunk.type for chunk in chunks}

    assert "clause-1" in ids
    assert any(item.startswith("clause-2-part") for item in ids)
    assert "finding-1" in ids
    assert "check-lease_deposit_cap" in ids
    assert "missing-handover" in ids
    assert "rewrite-clause-2" in ids
    assert "decision-1" in ids
    assert types == {"clause", "finding", "statutory_check", "missing_clause", "rewrite", "decision"}


@pytest.mark.asyncio
async def test_chat_retrieve_modes_thresholds_and_lexical_fallback() -> None:
    report = _sample_report()
    embedder = FakeEmbedder()
    index = await build_index(report, embedder, max_chars=800)

    hybrid = await retrieve(index, "Depozitomu geri alabilir miyim?", embedder, mode="hybrid")
    assert hybrid.mode == "hybrid"
    assert any("clause-2" in item.chunk.id or item.chunk.id == "finding-1" for item in hybrid.chunks)

    dense = await retrieve(index, "Depozito sınırı nedir?", embedder, mode="dense")
    assert dense.mode == "dense"
    assert dense.chunks

    lexical = await retrieve(index, "Depozito sınırı nedir?", embedder, mode="lexical")
    assert lexical.mode == "lexical"
    assert lexical.chunks

    out_of_scope = await retrieve(index, "evcil hayvan besleyebilir miyim?", embedder, mode="hybrid")
    assert out_of_scope.chunks == []

    raw = await retrieve(
        index, "evcil hayvan besleyebilir miyim?", embedder, mode="hybrid", apply_threshold=False
    )
    assert len(raw.chunks) > 0

    fallback = await retrieve(index, "Depozito sınırı nedir?", FailingEmbedder(), mode="hybrid")
    assert fallback.dense_failed is True
    assert fallback.mode == "lexical"
    assert fallback.chunks


def test_chat_session_store_ttl_capacity_and_history() -> None:
    now = [1000.0]
    store = ChatSessionStore(ttl_seconds=60, max_sessions=1, history_turns=2, clock=lambda: now[0])
    from law_rag.chat_index import ChatIndex

    idx = ChatIndex(chunks=[Chunk("clause-1", "clause", "Metin.")])
    session = store.create(idx)
    assert len(store) == 1

    with pytest.raises(SessionLimitReached):
        store.create(idx)

    store.record(session, Turn("q1", "a1"))
    store.record(session, Turn("q2", "a2"))
    store.record(session, Turn("q3", "a3"))
    assert [turn.question for turn in session.recent_history()] == ["q2", "q3"]

    now[0] += 30
    store.touch(session)
    now[0] += 40
    assert store.get(session.id).id == session.id

    now[0] += 61
    with pytest.raises(SessionNotFound):
        store.get(session.id)
    assert len(store) == 0


@pytest.mark.asyncio
async def test_gemini_chat_answerer_validates_citations_and_statutes(monkeypatch) -> None:
    chunks = [
        Chunk("clause-2", "clause", "Depozito 100.000 TL olarak belirlenmiştir.", "clause-2", "MADDE 2"),
        Chunk("check-lease_deposit_cap", "statutory_check", "6098 sayılı TBK m.342 sınırı 3 aydır.", "clause-2"),
    ]

    ok_answerer, _ = _build_gemini_answerer(
        monkeypatch, ["Depozitonuz 100.000 TL'dir [clause-2, clause-999]."]
    )
    ok_draft = await ok_answerer.answer("Depozitom ne kadar?", [], chunks)
    assert ok_draft.answered_by == "llm"
    assert ok_draft.cited_ids == ["clause-2"]
    assert "clause-999" not in ok_draft.text

    statute_answerer, capture = _build_gemini_answerer(
        monkeypatch,
        [
            "TBK m.999 uyarınca iade edilir [clause-2].",
            "TBK m.888 uyarınca iade edilir [clause-2].",
        ],
    )
    stripped = await statute_answerer.answer("Depozito nasıl iade edilir?", [], chunks)
    assert len(capture.prompts) == 2
    assert stripped.answered_by == "llm"
    assert "ilgili kanun hükmü" in stripped.text
    assert NOTE_STATUTE_STRIPPED in stripped.notes

    bad_cite_answerer, _ = _build_gemini_answerer(monkeypatch, ["Kaynak dışı yanıt [clause-999].", "Kaynaksız."])
    extractive = await bad_cite_answerer.answer("Depozito?", [], chunks)
    assert extractive.answered_by == "extractive"
    assert NOTE_EXTRACTIVE_FALLBACK in extractive.notes

    oob_answerer, _ = _build_gemini_answerer(monkeypatch, ["KAPSAM_DIŞI"])
    oob = await oob_answerer.answer("Bilinmeyen?", [], chunks)
    assert oob.covered is False
    assert oob.answered_by == "not_covered"

    prose_num_chunks = [
        Chunk("clause-1", "clause", "Kiracı 5 aylık kira bedeli depozito öder.", "clause-1", "MADDE 1"),
    ]
    hallucinated_num, num_capture = _build_gemini_answerer(
        monkeypatch,
        [
            "TBK m.5 uyarınca sınır vardır [clause-1].",
            "TBK m.5 gereğince sınır vardır [clause-1].",
        ],
    )
    stripped_num = await hallucinated_num.answer("Depozito kaç aylık?", [], prose_num_chunks)
    assert len(num_capture.prompts) == 2
    assert "TBK m.5" not in stripped_num.text
    assert NOTE_STATUTE_STRIPPED in stripped_num.notes


@pytest.mark.asyncio
async def test_chat_http_endpoints_lifecycle_and_errors(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_MAX_SESSIONS", "1")
    app = create_app(use_fake_clients=True)
    report_json = _sample_report().model_dump_json()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        bad_json = await client.post("/api/v1/chat/sessions", content="{}")
        assert bad_json.status_code == 422
        assert bad_json.json()["detail"]["code"] == "invalid_report"

        no_clauses = _sample_report().model_copy(update={"clauses": []}).model_dump_json()
        empty_res = await client.post("/api/v1/chat/sessions", content=no_clauses)
        assert empty_res.status_code == 400
        assert empty_res.json()["detail"]["code"] == "no_clauses"

        created = await client.post("/api/v1/chat/sessions", content=report_json)
        assert created.status_code == 201
        session_id = created.json()["session_id"]
        assert created.json()["disclaimer"] == DISCLAIMER

        limit_res = await client.post("/api/v1/chat/sessions", content=report_json)
        assert limit_res.status_code == 429
        assert limit_res.json()["detail"]["code"] == "chat_session_limit"

        empty_q = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages", json={"question": "   "}
        )
        assert empty_q.status_code == 422
        assert empty_q.json()["detail"]["code"] == "empty_question"

        covered = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"question": "Depozito sınırı nedir?"},
        )
        assert covered.status_code == 200
        body = covered.json()
        assert body["covered"] is True
        assert body["answered_by"] == "extractive"
        assert len(body["citations"]) > 0

        not_cov = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"question": "Evcil hayvan besleyebilir miyim?"},
        )
        assert not_cov.status_code == 200
        assert not_cov.json()["covered"] is False
        assert not_cov.json()["answered_by"] == "not_covered"

        deleted = await client.delete(f"/api/v1/chat/sessions/{session_id}")
        assert deleted.status_code == 204

        missing = await client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"question": "Depozito?"},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "chat_session_not_found"


@pytest.mark.asyncio
async def test_calibrated_chat_thresholds_for_short_queries_and_gemini() -> None:
    from law_rag.embeddings import GeminiEmbedder

    assert GeminiEmbedder.default_min_similarity == 0.65

    embedder = FakeEmbedder()
    index = await build_index(_sample_report(), embedder, max_chars=800)

    short_deposit = await retrieve(index, "depozito", embedder, mode="lexical")
    assert short_deposit.chunks

    short_rent = await retrieve(index, "kira ne kadar?", embedder, mode="lexical")
    assert short_rent.chunks

    oob_partial = await retrieve(index, "evcil hayvan sözleşmesi", embedder, mode="lexical")
    assert oob_partial.chunks == []
