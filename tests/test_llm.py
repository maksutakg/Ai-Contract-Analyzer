import pytest

from law_rag.analyzer_base import (
    CLAUSE_REWRITE_FALLBACK_WARNING,
    FACTS_FALLBACK_WARNING,
    GRADE_FALLBACK_WARNING,
    MISSING_CLAUSES_FALLBACK_WARNING,
)
from law_rag.llm import FakeContractAnalyzer, GeminiContractAnalyzer, merge_findings, normalize_risk_findings
from law_rag.llm_steps import cites_statute
from law_rag.models import Clause, RiskFinding, YargiDecision


class PromptCapture:
    def __init__(self, responses: str | list[str]) -> None:
        self.responses = [responses] if isinstance(responses, str) else list(responses)
        self.contents: list[str] = []

    async def generate_content(self, *, model: str, contents: str):
        self.contents.append(contents)
        reply = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

        class Response:
            text = reply

        return Response()


class FakeGeminiClient:
    def __init__(self, capture: PromptCapture) -> None:
        self.aio = type("Aio", (), {"models": capture})()


def _test_settings(**extra):
    attrs = {"gemini_api_key": "test", "gemini_model": "gemini-test", **extra}
    return type("Settings", (), attrs)()


@pytest.mark.asyncio
async def test_segment_clauses_groups_contract_articles() -> None:
    analyzer = FakeContractAnalyzer()
    text = """
HIZMET SOZLESMESI
Sozlesme No: SZL-2024-00847
MADDE 1 - SOZLESMENIN KONUSU
Yuklenici e-ticaret altyapisini modernize eder.
ERP entegrasyonu ve mobil uygulama gelistirme islerini teslim eder.
MADDE 2 - SOZLESME BEDELI
Odeme Kalemi
Tutar
Pesinat
450.000 TL
MADDE 3 - FESIH
Kilit personelin tamamının degismesi halinde derhal fesih hakki dogar.
"""

    clauses = await analyzer.segment_clauses(text)

    assert [clause.id for clause in clauses] == ["preamble", "clause-1", "clause-2", "clause-3"]
    assert clauses[0].title == "Başlangıç"
    assert "Sozlesme No" in clauses[0].text
    assert clauses[1].title == "MADDE 1 - SOZLESMENIN KONUSU"
    assert "ERP entegrasyonu" in clauses[1].text
    assert "Odeme Kalemi" in clauses[2].text
    assert all("Sozlesme No" not in clause.text for clause in clauses[1:])


@pytest.mark.asyncio
async def test_build_legal_queries_uses_service_contract_terms() -> None:
    analyzer = FakeContractAnalyzer()
    findings = [
        RiskFinding(
            id="finding-1",
            category="intellectual_property",
            severity="medium",
            explanation="Hak devri final odemeye bagli.",
            recommendation="Hak devrini netlestirin.",
            confidence=0.9,
        ),
        RiskFinding(
            id="finding-2",
            category="termination",
            severity="high",
            explanation="Kilit personel degisikliginde derhal fesih.",
            recommendation="Kilit personel ve cure period tanimlayin.",
            confidence=0.9,
        ),
        RiskFinding(
            id="finding-3",
            category="data_protection",
            severity="critical",
            explanation="KVKK sorumlulugu reddediliyor.",
            recommendation="KVKK yukumluluklerini netlestirin.",
            confidence=1.0,
        ),
    ]

    queries = await analyzer.build_legal_queries(findings, contract_type="service")

    assert isinstance(queries, dict)
    assert set(queries) == {"finding-1", "finding-2", "finding-3"}
    joined = " ".join(queries.values())
    assert "kira sozlesmesi" not in joined
    assert "fikri mülkiyet" in queries["finding-1"]
    assert "hizmet sözleşmesi" in queries["finding-2"] and "fesih" in queries["finding-2"]
    assert "KVKK" in queries["finding-3"]


@pytest.mark.asyncio
async def test_build_legal_queries_uses_turkish_search_terms_for_yargi() -> None:
    analyzer = FakeContractAnalyzer()
    findings = [
        RiskFinding(
            id="finding-1",
            category="data_protection",
            severity="critical",
            explanation="KVKK veri işleyen sorumluluğu reddediliyor.",
            recommendation="KVKK yükümlülüklerini netleştirin.",
            confidence=1.0,
        ),
        RiskFinding(
            id="finding-2",
            category="intellectual_property",
            severity="medium",
            explanation="Fikri mülkiyet hak devri belirsiz.",
            recommendation="Hak devrini netleştirin.",
            confidence=0.9,
        ),
        RiskFinding(
            id="finding-3",
            category="force_majeure",
            severity="low",
            explanation="Mücbir sebep tanımı belirsiz.",
            recommendation="Tanımı daraltın.",
            confidence=0.8,
        ),
    ]

    queries = await analyzer.build_legal_queries(findings, contract_type="service")

    assert '"veri işleyen"' in queries["finding-1"]
    assert '"hizmet sözleşmesi"' in queries["finding-1"]
    assert '"fikri mülkiyet"' in queries["finding-2"]
    assert '"mücbir sebep"' in queries["finding-3"]


def test_normalize_risk_findings_refines_generic_categories() -> None:
    findings = [
        RiskFinding(
            id="finding-1",
            category="cash_payment",
            severity="medium",
            explanation="Aylik %3 gecikme faizi finansal risk dogurur.",
            recommendation="Faiz oranini dusurun.",
        ),
        RiskFinding(
            id="finding-2",
            category="general_risk",
            severity="medium",
            explanation="Genel amacli framework tanimi belirsiz ve fikri mulkiyet devri tartismali.",
            recommendation="Hak devri ve framework kapsamlarini tanimlayin.",
        ),
        RiskFinding(
            id="finding-3",
            category="general_risk",
            severity="medium",
            explanation="Diger olaganustu durumlar ifadesi mucbir sebep kapsaminda belirsiz.",
            recommendation="Pandemi ve siber saldiri gibi olaylari acikca sayin.",
        ),
    ]

    normalized = normalize_risk_findings(findings)

    assert [finding.category for finding in normalized] == [
        "payment_interest",
        "intellectual_property",
        "force_majeure",
    ]


@pytest.mark.asyncio
async def test_gemini_summary_prompt_is_compact(monkeypatch) -> None:
    capture = PromptCapture("Kisa ozet")
    monkeypatch.setattr("law_rag.llm.genai.Client", lambda api_key: FakeGeminiClient(capture))
    analyzer = GeminiContractAnalyzer(_test_settings())

    await analyzer.summarize_contract("Madde\n" * 4000, contract_type="service")

    assert len(capture.contents) > 1
    assert all(len(prompt) < 10000 for prompt in capture.contents)
    assert "This is part 1" in capture.contents[0]
    assert "120-180 words" in capture.contents[-1]
    assert "Do not include risk analysis" in capture.contents[-1]


@pytest.mark.asyncio
async def test_gemini_risk_prompt_limits_findings_and_field_lengths(monkeypatch) -> None:
    capture = PromptCapture("[]")
    monkeypatch.setattr("law_rag.llm.genai.Client", lambda api_key: FakeGeminiClient(capture))
    analyzer = GeminiContractAnalyzer(_test_settings())
    clauses = [
        Clause(id=f"clause-{index}", text="uzun madde metni " * 80)
        for index in range(1, 20)
    ]

    await analyzer.classify_risks(clauses, contract_type="service")

    prompt = capture.contents[0]
    assert len(capture.contents) > 1
    assert len(prompt) < 10000
    assert "Return at most 6 findings" in prompt
    assert "explanation under 240 characters" in prompt
    assert "recommendation under 240 characters" in prompt


@pytest.mark.asyncio
async def test_gemini_build_legal_queries_sends_prompt(monkeypatch) -> None:
    capture = PromptCapture("optimized query")
    monkeypatch.setattr("law_rag.llm.genai.Client", lambda api_key: FakeGeminiClient(capture))
    analyzer = GeminiContractAnalyzer(_test_settings())
    findings = [
        RiskFinding(
            id="finding-1",
            category="data_protection",
            severity="critical",
            explanation="KVKK sorumlulugu reddediliyor.",
            recommendation="Sorumluluk reddini kaldirin.",
            confidence=1.0,
        )
    ]

    queries = await analyzer.build_legal_queries(findings)

    assert queries == {"finding-1": "optimized query"}
    assert "optimized search query" in capture.contents[0]


@pytest.mark.asyncio
async def test_gemini_grade_decisions_falls_back_per_missing_item(monkeypatch) -> None:
    capture = PromptCapture('[{"index": 1, "label": "ilgili", "reason": "Aynı konu."}]')
    monkeypatch.setattr("law_rag.llm.genai.Client", lambda api_key: FakeGeminiClient(capture))
    analyzer = GeminiContractAnalyzer(_test_settings())
    finding = RiskFinding(
        id="finding-1",
        category="deposit_forfeiture",
        severity="high",
        explanation="Depozito iade edilmiyor.",
        recommendation="Düzenleyin.",
    )
    decisions = [
        YargiDecision(source="test", title="Karar 1", relevance="q", excerpt="Depozito iade edilmez."),
        YargiDecision(source="test", title="Karar 2", relevance="q", excerpt="Farklı konu."),
    ]

    assessments = await analyzer.grade_decisions(finding, decisions)

    assert assessments[0].grade == "relevant"
    assert assessments[0].graded_by == "llm"
    assert assessments[1].graded_by == "keyword"
    assert GRADE_FALLBACK_WARNING in analyzer.drain_warnings()


@pytest.mark.asyncio
async def test_gemini_rewrite_query_falls_back_when_model_repeats_itself(monkeypatch) -> None:
    capture = PromptCapture('"depozito" "kira"')
    monkeypatch.setattr("law_rag.llm.genai.Client", lambda api_key: FakeGeminiClient(capture))
    analyzer = GeminiContractAnalyzer(_test_settings())
    finding = RiskFinding(
        id="finding-1",
        category="deposit_forfeiture",
        severity="high",
        explanation="Depozito iade edilmiyor.",
        recommendation="Düzenleyin.",
    )

    rewritten = await analyzer.rewrite_query(finding, ['"depozito" "kira"'], "Sonuç yok")

    assert rewritten == "depozito kira"


def test_merge_findings_deduplicates_clause_and_rule_based_categories() -> None:
    merged = merge_findings(
        [
            RiskFinding(
                id="f1",
                category="termination",
                severity="medium",
                explanation="Orta fesih",
                recommendation="Düzeltin",
                confidence=0.7,
                clause_id="clause-1",
                detected_by="llm",
            ),
            RiskFinding(
                id="f2",
                category="termination",
                severity="high",
                explanation="Yüksek fesih",
                recommendation="Düzeltin",
                confidence=0.9,
                clause_id="clause-1",
                detected_by="llm",
            ),
            RiskFinding(
                id="f3",
                category="penalty_clause",
                severity="medium",
                explanation="Cezai şart 1",
                recommendation="Düzeltin",
                clause_id="clause-2",
                detected_by="rule_based",
            ),
            RiskFinding(
                id="f4",
                category="penalty_clause",
                severity="medium",
                explanation="Cezai şart 2",
                recommendation="Düzeltin",
                clause_id="clause-3",
                detected_by="rule_based",
            ),
        ]
    )

    assert [f.id for f in merged] == ["finding-1", "finding-2"]
    assert merged[0].severity == "high"
    assert merged[1].category == "penalty_clause"


def test_cites_statute_detects_law_and_article_numbers() -> None:
    assert cites_statute("6098 sayılı Kanun uyarınca")
    assert cites_statute("TBK m.342 gereğince")
    assert cites_statute("Türk Borçlar Kanunu'nun 344. maddesi")
    assert not cites_statute("Üç aylık kira bedeli sınırına uyulmalıdır.")


@pytest.mark.asyncio
async def test_gemini_suggest_rewrites_rejects_statute_citations_and_falls_back(monkeypatch) -> None:
    payload = '[{"clause_id": "clause-1", "suggested_text": "TBK m.342 uyarınca depozito alınır.", "rationale": "Yasal sınır."}]'
    capture = PromptCapture(payload)
    monkeypatch.setattr("law_rag.llm.genai.Client", lambda api_key: FakeGeminiClient(capture))
    analyzer = GeminiContractAnalyzer(_test_settings())
    clause = Clause(id="clause-1", title="MADDE 1", text="Depozito iade edilmez.")
    finding = RiskFinding(
        id="finding-1",
        category="deposit_forfeiture",
        severity="high",
        explanation="Depozito riski",
        recommendation="Düzenleyin",
        clause_id="clause-1",
    )

    rewrites = await analyzer.suggest_rewrites([(clause, [finding])], "lease", "tenant")

    assert len(rewrites) == 1
    assert rewrites[0].generated_by == "rule_based"
    assert "TBK m.342" not in rewrites[0].suggested_text
    assert CLAUSE_REWRITE_FALLBACK_WARNING in analyzer.drain_warnings()


@pytest.mark.asyncio
async def test_gemini_extra_steps_warn_on_malformed_json(monkeypatch) -> None:
    capture = PromptCapture("not json")
    monkeypatch.setattr("law_rag.llm.genai.Client", lambda api_key: FakeGeminiClient(capture))
    analyzer = GeminiContractAnalyzer(_test_settings())
    clauses = [Clause(id="clause-1", title="MADDE 1", text="Kiracı 100.000 TL depozito öder.")]

    facts = await analyzer.extract_contract_facts(clauses, "lease")
    assert any(fact.name == "deposit_amount" and fact.value == 100000.0 for fact in facts)
    assert FACTS_FALLBACK_WARNING in analyzer.drain_warnings()

    presence = await analyzer.detect_missing_clauses(clauses, "lease")
    assert "deposit" in presence
    assert MISSING_CLAUSES_FALLBACK_WARNING in analyzer.drain_warnings()


def test_genai_clients_disable_automatic_retries(monkeypatch) -> None:
    from law_rag.chat_answer import GeminiChatAnswerer
    from law_rag.config import Settings
    from law_rag.embeddings import GeminiEmbedder
    from law_rag.ocr import GeminiOcrEngine

    seen_options = []

    def fake_client(*, api_key: str, http_options=None):
        seen_options.append(http_options)
        return FakeGeminiClient(PromptCapture("ok"))

    monkeypatch.setattr("google.genai.Client", fake_client)
    settings = Settings(_env_file=None, gemini_api_key="test-key")

    GeminiContractAnalyzer(settings)
    GeminiEmbedder(settings)
    GeminiOcrEngine(settings)
    GeminiChatAnswerer(settings)

    assert len(seen_options) == 4
    assert all(opt is not None for opt in seen_options)
    assert all(opt.retry_options is not None and opt.retry_options.attempts == 1 for opt in seen_options)


@pytest.mark.asyncio
async def test_gemini_classify_risks_strips_hallucinated_statutes_from_explanation_and_recommendation(
    monkeypatch,
) -> None:
    reply = (
        '[{"category": "deposit_forfeiture", "severity": "high", '
        '"explanation": "TBK m.342 ve 6098 sayılı Kanun uyarınca 5 aylık depozito aşırıdır.", '
        '"recommendation": "Türk Borçlar Kanunu 342. maddesi sınırına indirin.", '
        '"confidence": 0.9, "clause_id": "clause-1", "disadvantaged_party": "tenant"}, '
        '{"category": "termination", "severity": "medium", '
        '"explanation": "6098 sayılı Kanun m.347 metinde geçmektedir.", '
        '"recommendation": "Madde 2 ile uyumlu hale getirin.", '
        '"confidence": 0.8, "clause_id": "clause-2", "disadvantaged_party": "tenant"}]'
    )
    capture = PromptCapture(reply)
    monkeypatch.setattr("law_rag.llm.genai.Client", lambda api_key: FakeGeminiClient(capture))
    analyzer = GeminiContractAnalyzer(_test_settings())
    clauses = [
        Clause(id="clause-1", title="MADDE 1", text="Kiracı 5 aylık kira tutarında 100.000 TL depozito öder."),
        Clause(id="clause-2", title="MADDE 2", text="Taraflar 6098 sayılı Kanun m.347 uyarınca fesih yapabilir."),
    ]

    findings = await analyzer.classify_risks(clauses, contract_type="lease", party="tenant")

    f1 = next(f for f in findings if f.clause_id == "clause-1")
    f2 = next(f for f in findings if f.clause_id == "clause-2")
    assert "TBK m.342" not in f1.explanation
    assert "6098 sayılı" not in f1.explanation
    assert "342." not in f1.recommendation
    assert "ilgili kanun hükmü" in f1.explanation
    assert "6098 sayılı" in f2.explanation
    assert "m.347" in f2.explanation
