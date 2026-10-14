import asyncio

from law_rag.config import Settings
from law_rag.graph import (
    NO_RELEVANT_DECISION_LIMITATION,
    RETRIEVAL_TIMEOUT_LIMITATION,
    analyze_contract,
    select_related_decisions,
    is_relevant_decision,
)
from law_rag.models import Clause, RiskFinding, YargiDecision
import pytest


class AnalyzerWithGenericCategories:
    async def summarize_contract(self, text: str, contract_type: str | None = None) -> str:
        return "summary"

    async def segment_clauses(self, text: str) -> list[Clause]:
        return [Clause(id="clause-1", title="MADDE 1", text=text)]

    async def classify_risks(
        self,
        clauses: list[Clause],
        contract_type: str | None = None,
    ) -> list[RiskFinding]:
        return [
            RiskFinding(
                id="finding-1",
                category="general_risk",
                severity="medium",
                explanation="Framework tanimi belirsiz ve fikri mulkiyet devri tartismali.",
                recommendation="Framework ve hak devri kapsamlarini netlestirin.",
                confidence=0.9,
                clause_id="clause-1",
            ),
            RiskFinding(
                id="finding-2",
                category="cash_payment",
                severity="medium",
                explanation="Aylik %3 gecikme faizi yuksek.",
                recommendation="Faiz oranini dusurun.",
                confidence=0.9,
                clause_id="clause-1",
            ),
        ]

    async def build_legal_queries(self, findings: list[RiskFinding]) -> list[str]:
        return [f"{finding.category} query" for finding in findings]


class NoisyYargiClient:
    def __init__(self) -> None:
        self.fetched_titles: list[str] = []

    async def search(self, query: str, category: str | None = None) -> list[YargiDecision]:
        if query.startswith("intellectual_property"):
            return [
                YargiDecision(source="test", title="empty old", relevance=query),
                YargiDecision(
                    source="test",
                    title="with excerpt",
                    relevance=query,
                    excerpt="Yazılım lisansı ve fikri mülkiyet hak devri tartışılmıştır.",
                ),
                YargiDecision(source="test", title="empty new", relevance=query),
            ]
        return [
            YargiDecision(source="test", title="only metadata 1", relevance=query, excerpt="Gecikme faizi ve temerrüt incelenmiştir."),
            YargiDecision(source="test", title="only metadata 2", relevance=query),
        ]

    async def fetch_decision_text(self, decision: YargiDecision) -> str | None:
        self.fetched_titles.append(decision.title)
        return f"Fetched text for {decision.title}"


@pytest.mark.asyncio
async def test_analyze_contract_normalizes_findings_and_prioritizes_decisions() -> None:
    yargi_client = NoisyYargiClient()
    report = await analyze_contract(
        file_name="contract.docx",
        file_type="docx",
        raw_text="contract text",
        contract_type="service",
        analyzer=AnalyzerWithGenericCategories(),
        yargi_client=yargi_client,
    )

    assert [finding.category for finding in report.findings] == [
        "intellectual_property",
        "payment_interest",
    ]
    assert len(report.related_decisions) == 2
    assert report.related_decisions[0].title == "with excerpt"
    assert report.related_decisions[0].excerpt == "Yazılım lisansı ve fikri mülkiyet hak devri tartışılmıştır."
    assert report.related_decisions[1].title == "only metadata 1"
    assert report.related_decisions[1].excerpt == "Gecikme faizi ve temerrüt incelenmiştir."
    assert yargi_client.fetched_titles == []
    assert "Some Yargi MCP results had no excerpt and were deprioritized." in report.limitations


def test_select_related_decisions_filters_category_mismatches() -> None:
    decisions, limitations = select_related_decisions(
        {
            "finding-1": [
                YargiDecision(
                    finding_id="finding-1",
                    finding_category="intellectual_property",
                    source="test",
                    title="Hak devri uyuşmazlığı",
                    relevance="query",
                    excerpt="Kaçak elektrik faturası ve menfi tespit davası hakkındadır.",
                ),
                YargiDecision(
                    finding_id="finding-1",
                    finding_category="intellectual_property",
                    source="test",
                    title="Yazılım lisansı ve fikri mülkiyet",
                    relevance="query",
                    excerpt="Taraflar arasında yazılım hak devri ve lisans kapsamı tartışılmıştır.",
                ),
            ],
            "finding-2": [
                YargiDecision(
                    finding_id="finding-2",
                    finding_category="termination",
                    source="test",
                    title="Ortaklıktan çıkma",
                    relevance="query",
                    excerpt="Limited şirket müdürünün azli ve kayyım atanması incelenmiştir.",
                ),
            ],
        }
    )

    assert [decision.title for decision in decisions] == ["Yazılım lisansı ve fikri mülkiyet"]
    assert NO_RELEVANT_DECISION_LIMITATION in limitations


def test_is_relevant_decision_is_character_insensitive() -> None:
    decision = YargiDecision(
        finding_id="finding-1",
        finding_category="data_protection",
        source="test",
        title="Veri ihlali",
        relevance="test",
        excerpt="kisisel verilerin korunmasi kanunu kapsamında veri sorumlusu yukumlulugu.",
    )
    assert is_relevant_decision(decision) is True


class CountingAnalyzer(AnalyzerWithGenericCategories):
    def __init__(self) -> None:
        self.query_calls = 0

    async def build_legal_queries(self, findings: list[RiskFinding]) -> list[str]:
        self.query_calls += 1
        return await super().build_legal_queries(findings)


class TitleOnlyYargiClient:
    def __init__(self) -> None:
        self.fetched_titles: list[str] = []

    async def search(self, query: str, category: str | None = None) -> list[YargiDecision]:
        title = "Yazılım lisans" if category == "intellectual_property" else "Gecikme faizi temerrüt"
        return [YargiDecision(source="test", title=title, relevance=query)]

    async def fetch_decision_text(self, decision: YargiDecision) -> str | None:
        self.fetched_titles.append(decision.title)
        return "karar metni"


@pytest.mark.asyncio
@pytest.mark.parametrize("fetch_documents", [False, True])
async def test_queries_built_once_per_finding_and_fetch_flag_respected(fetch_documents: bool) -> None:
    analyzer = CountingAnalyzer()
    yargi_client = TitleOnlyYargiClient()
    report = await analyze_contract(
        file_name="contract.docx",
        file_type="docx",
        raw_text="contract text",
        analyzer=analyzer,
        yargi_client=yargi_client,
        app_settings=Settings(YARGI_FETCH_DOCUMENTS=fetch_documents),
    )

    assert analyzer.query_calls == len(report.findings) == 2
    assert len(report.related_decisions) == 2
    expected = ["Yazılım lisans", "Gecikme faizi temerrüt"] if fetch_documents else []
    assert yargi_client.fetched_titles == expected


class SlowYargiClient:
    async def search(self, query: str, category: str | None = None) -> list[YargiDecision]:
        if category == "intellectual_property":
            await asyncio.sleep(5)
        return [YargiDecision(source="test", title="Gecikme faizi temerrüt", relevance=query)]


@pytest.mark.asyncio
async def test_retrieval_keeps_partial_results_after_total_timeout() -> None:
    report = await analyze_contract(
        file_name="contract.docx",
        file_type="docx",
        raw_text="contract text",
        analyzer=AnalyzerWithGenericCategories(),
        yargi_client=SlowYargiClient(),
        app_settings=Settings(YARGI_TOTAL_TIMEOUT_SECONDS=0.2),
    )

    assert [decision.title for decision in report.related_decisions] == ["Gecikme faizi temerrüt"]
    assert RETRIEVAL_TIMEOUT_LIMITATION in report.limitations


class AnalyzerWithLimitations(AnalyzerWithGenericCategories):
    limitations = ["analyzer note"]


@pytest.mark.asyncio
async def test_analyzer_limitations_are_reported() -> None:
    report = await analyze_contract(
        file_name="contract.docx",
        file_type="docx",
        raw_text="contract text",
        analyzer=AnalyzerWithLimitations(),
        yargi_client=TitleOnlyYargiClient(),
    )

    assert "analyzer note" in report.limitations
