import pytest

from law_rag.llm import FakeContractAnalyzer, GeminiContractAnalyzer, normalize_risk_findings
from law_rag.models import Clause, RiskFinding


class PromptCapture:
    def __init__(self, text: str) -> None:
        self.text = text
        self.contents: list[str] = []

    async def generate_content(self, *, model: str, contents: str):
        self.contents.append(contents)

        class Response:
            text = self.text

        return Response()


class FakeGeminiClient:
    def __init__(self, capture: PromptCapture) -> None:
        self.aio = type("Aio", (), {"models": capture})()


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

    assert [clause.id for clause in clauses] == ["clause-1", "clause-2", "clause-3"]
    assert clauses[0].title == "MADDE 1 - SOZLESMENIN KONUSU"
    assert "ERP entegrasyonu" in clauses[0].text
    assert "Odeme Kalemi" in clauses[1].text
    assert all("Sozlesme No" not in clause.text for clause in clauses)


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

    queries = await analyzer.build_legal_queries(findings)

    joined = " ".join(queries)
    assert "kira sozlesmesi" not in joined
    assert any("fikri mülkiyet" in query for query in queries)
    assert any("hizmet sözleşmesi" in query and "fesih" in query for query in queries)
    assert any("KVKK" in query or "kisisel veri" in query for query in queries)


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

    queries = await analyzer.build_legal_queries(findings)

    assert '"veri işleyen"' in queries[0]
    assert '"hizmet sözleşmesi"' in queries[0]
    assert '"fikri mülkiyet"' in queries[1]
    assert '"mücbir sebep"' in queries[2]


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
    monkeypatch.setattr(
        "law_rag.llm.genai.Client",
        lambda api_key: FakeGeminiClient(capture),
    )
    analyzer = GeminiContractAnalyzer(
        type("Settings", (), {"gemini_api_key": "test", "gemini_model": "gemini-test"})()
    )

    await analyzer.summarize_contract("Madde\n" * 4000, contract_type="service")

    prompt = capture.contents[0]
    assert len(prompt) < 7000
    assert "120-180 words" in prompt
    assert "Do not include risk analysis" in prompt


@pytest.mark.asyncio
async def test_gemini_risk_prompt_limits_findings_and_field_lengths(monkeypatch) -> None:
    capture = PromptCapture("[]")
    monkeypatch.setattr(
        "law_rag.llm.genai.Client",
        lambda api_key: FakeGeminiClient(capture),
    )
    analyzer = GeminiContractAnalyzer(
        type("Settings", (), {"gemini_api_key": "test", "gemini_model": "gemini-test"})()
    )
    clauses = [
        Clause(id=f"clause-{index}", text="uzun madde metni " * 80)
        for index in range(1, 20)
    ]

    await analyzer.classify_risks(clauses, contract_type="service")

    prompt = capture.contents[0]
    assert len(prompt) < 10000
    assert "Return at most 6 findings" in prompt
    assert "explanation under 240 characters" in prompt
    assert "recommendation under 240 characters" in prompt


@pytest.mark.asyncio
async def test_gemini_build_legal_queries_sends_prompt(monkeypatch) -> None:
    capture = PromptCapture("optimized query")
    monkeypatch.setattr(
        "law_rag.llm.genai.Client",
        lambda api_key: FakeGeminiClient(capture),
    )
    analyzer = GeminiContractAnalyzer(
        type("Settings", (), {"gemini_api_key": "test", "gemini_model": "gemini-test"})()
    )
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
    assert queries == ["optimized query"]
    assert "optimized search query" in capture.contents[0]
