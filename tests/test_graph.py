import pytest

from law_rag.config import Settings
from law_rag.crag import (
    AMBIGUOUS_DECISION_LIMITATION,
    KEYWORD_ONLY_LIMITATION,
    NO_RELEVANT_DECISION_LIMITATION,
    RETRIEVAL_FAILED_LIMITATION,
)
from law_rag.graph import analyze_contract, is_relevant_decision, select_related_decisions
from law_rag.models import Clause, DecisionAssessment, RiskFinding, YargiDecision


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

    async def build_legal_queries(
        self, findings: list[RiskFinding], contract_type: str | None = None
    ) -> dict[str, str]:
        return {finding.id: f"{finding.category} query" for finding in findings}

    async def grade_decisions(
        self, finding: RiskFinding, decisions: list[YargiDecision]
    ) -> list[DecisionAssessment]:
        return [
            DecisionAssessment(grade="relevant", reason="İlgili karar.", graded_by="llm")
            for _ in decisions
        ]

    async def rewrite_query(
        self,
        finding: RiskFinding,
        previous_queries: list[str],
        feedback: str,
        contract_type: str | None = None,
    ) -> str:
        return ""


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
            YargiDecision(
                source="test",
                title="only metadata 1",
                relevance=query,
                excerpt="Gecikme faizi ve temerrüt incelenmiştir.",
            ),
            YargiDecision(source="test", title="only metadata 2", relevance=query),
        ]

    async def fetch_decision_text(self, decision: YargiDecision) -> str | None:
        self.fetched_titles.append(decision.title)
        return None


class SingleFindingAnalyzer:
    def __init__(self, rewritten_queries: list[str] | None = None) -> None:
        self.rewritten_queries = list(rewritten_queries or [])
        self.rewrite_calls = 0
        self.grade_calls = 0

    async def summarize_contract(self, text: str, contract_type: str | None = None) -> str:
        return "Özet"

    async def segment_clauses(self, text: str) -> list[Clause]:
        return [Clause(id="clause-1", title="MADDE 1", text=text)]

    async def classify_risks(
        self, clauses: list[Clause], contract_type: str | None = None
    ) -> list[RiskFinding]:
        return [
            RiskFinding(
                id="finding-1",
                category="deposit_forfeiture",
                severity="high",
                explanation="Depozito iade edilmez.",
                recommendation="Depozito iade şartını ekleyin.",
                confidence=0.9,
                clause_id="clause-1",
            )
        ]

    async def build_legal_queries(
        self, findings: list[RiskFinding], contract_type: str | None = None
    ) -> dict[str, str]:
        return {"finding-1": "initial query"}

    async def grade_decisions(
        self, finding: RiskFinding, decisions: list[YargiDecision]
    ) -> list[DecisionAssessment]:
        self.grade_calls += 1
        results: list[DecisionAssessment] = []
        for decision in decisions:
            text = (decision.excerpt or "").lower()
            if "depozito" in text and "iade edilmez" in text:
                results.append(DecisionAssessment(grade="relevant", reason="Tam eşleşme.", graded_by="llm"))
            elif "depozito" in text:
                results.append(DecisionAssessment(grade="ambiguous", reason="Kısmi eşleşme.", graded_by="llm"))
            else:
                results.append(DecisionAssessment(grade="irrelevant", reason="İlgisiz.", graded_by="llm"))
        return results

    async def rewrite_query(
        self,
        finding: RiskFinding,
        previous_queries: list[str],
        feedback: str,
        contract_type: str | None = None,
    ) -> str:
        self.rewrite_calls += 1
        if self.rewritten_queries:
            return self.rewritten_queries.pop(0)
        return ""


class ScenarioYargiClient:
    def __init__(self, responses: dict[str, list[YargiDecision]], fail_query: str | None = None) -> None:
        self.responses = responses
        self.fail_query = fail_query
        self.searched_queries: list[str] = []
        self.fetched_titles: list[str] = []

    async def search(self, query: str, category: str | None = None) -> list[YargiDecision]:
        self.searched_queries.append(query)
        if self.fail_query and query == self.fail_query:
            raise RuntimeError("MCP down")
        return list(self.responses.get(query, []))

    async def fetch_decision_text(self, decision: YargiDecision) -> str | None:
        self.fetched_titles.append(decision.title)
        return "Depozito iade edilmez hükmü geçersizdir."


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
        app_settings=Settings(crag_max_fetches_per_round=1, crag_max_rewrites=0),
    )

    assert [finding.category for finding in report.findings] == [
        "intellectual_property",
        "payment_interest",
    ]
    assert len(report.related_decisions) == 2
    assert report.related_decisions[0].title == "with excerpt"
    assert report.related_decisions[1].title == "only metadata 1"
    assert len(yargi_client.fetched_titles) == 1


@pytest.mark.asyncio
async def test_crag_scenario_first_round_relevant_skips_rewrite() -> None:
    analyzer = SingleFindingAnalyzer(["unused rewrite"])
    yargi = ScenarioYargiClient(
        {
            "initial query": [
                YargiDecision(
                    source="Bedesten",
                    title="Doğrudan karar",
                    relevance="q",
                    excerpt="Depozito ve güvence bedeli iade edilmez kaydı geçersizdir.",
                )
            ]
        }
    )

    report = await analyze_contract(
        file_name="lease.docx",
        file_type="docx",
        raw_text="MADDE 1 - Depozito iade edilmez.",
        contract_type="lease",
        analyzer=analyzer,
        yargi_client=yargi,
    )

    assert analyzer.rewrite_calls == 0
    assert len(report.retrieval_trace) == 1
    trace = report.retrieval_trace[0]
    assert trace.status == "relevant"
    assert trace.rewrites_used == 0
    assert report.related_decisions[0].title == "Doğrudan karar"
    assert report.related_decisions[0].grade == "relevant"


@pytest.mark.asyncio
async def test_crag_scenario_rewrite_recovers_relevant_decision() -> None:
    analyzer = SingleFindingAnalyzer(["second query"])
    yargi = ScenarioYargiClient(
        {
            "initial query": [
                YargiDecision(
                    source="Bedesten",
                    title="Alakasız karar",
                    relevance="q",
                    excerpt="Elektrik faturası uyuşmazlığı.",
                )
            ],
            "second query": [
                YargiDecision(
                    source="Bedesten",
                    title="İkinci tur kararı",
                    relevance="q",
                    excerpt="Depozito iade edilmez hükmü hakkında Yargıtay kararı.",
                )
            ],
        }
    )

    report = await analyze_contract(
        file_name="lease.docx",
        file_type="docx",
        raw_text="MADDE 1 - Depozito iade edilmez.",
        contract_type="lease",
        analyzer=analyzer,
        yargi_client=yargi,
    )

    assert analyzer.rewrite_calls == 1
    assert yargi.searched_queries == ["initial query", "second query"]
    trace = report.retrieval_trace[0]
    assert trace.status == "relevant"
    assert trace.rewrites_used == 1
    assert len(trace.attempts) == 2
    assert report.related_decisions[0].title == "İkinci tur kararı"
    assert report.related_decisions[0].attempt == 2


@pytest.mark.asyncio
async def test_crag_scenario_exhausted_keeps_ambiguous_decision_and_limitations() -> None:
    analyzer = SingleFindingAnalyzer(["retry 1", "retry 2"])
    yargi = ScenarioYargiClient(
        {
            "initial query": [
                YargiDecision(
                    source="Bedesten",
                    title="Kısmi karar",
                    relevance="q",
                    excerpt="Depozito bedeli kira ilişkisinde incelenmiştir.",
                )
            ],
            "retry 1": [],
            "retry 2": [],
        }
    )

    report = await analyze_contract(
        file_name="lease.docx",
        file_type="docx",
        raw_text="MADDE 1 - Depozito iade edilmez.",
        contract_type="lease",
        analyzer=analyzer,
        yargi_client=yargi,
        app_settings=Settings(crag_max_rewrites=2),
    )

    trace = report.retrieval_trace[0]
    assert trace.status == "exhausted"
    assert trace.rewrites_used == 2
    assert report.related_decisions[0].title == "Kısmi karar"
    assert report.related_decisions[0].grade == "ambiguous"
    assert NO_RELEVANT_DECISION_LIMITATION in report.limitations
    assert AMBIGUOUS_DECISION_LIMITATION in report.limitations


@pytest.mark.asyncio
async def test_crag_search_failure_and_keyword_only_mode() -> None:
    analyzer = SingleFindingAnalyzer()
    yargi = ScenarioYargiClient({}, fail_query="initial query")

    report = await analyze_contract(
        file_name="lease.docx",
        file_type="docx",
        raw_text="MADDE 1 - Depozito iade edilmez.",
        contract_type="lease",
        analyzer=analyzer,
        yargi_client=yargi,
        app_settings=Settings(crag_use_llm_grader=False),
    )

    assert analyzer.grade_calls == 0
    assert report.retrieval_trace[0].status == "failed"
    assert RETRIEVAL_FAILED_LIMITATION in report.limitations
    assert KEYWORD_ONLY_LIMITATION in report.limitations


def test_select_related_decisions_filters_by_grade() -> None:
    decisions, limitations = select_related_decisions(
        {
            "finding-1": [
                YargiDecision(
                    finding_id="finding-1",
                    finding_category="intellectual_property",
                    source="test",
                    title="Hak devri uyuşmazlığı",
                    relevance="query",
                    excerpt="Kaçak elektrik faturası.",
                    grade="irrelevant",
                ),
                YargiDecision(
                    finding_id="finding-1",
                    finding_category="intellectual_property",
                    source="test",
                    title="Yazılım lisansı ve fikri mülkiyet",
                    relevance="query",
                    excerpt="Taraflar arasında yazılım hak devri ve lisans kapsamı tartışılmıştır.",
                    grade="relevant",
                ),
            ],
            "finding-2": [
                YargiDecision(
                    finding_id="finding-2",
                    finding_category="termination",
                    source="test",
                    title="Ortaklıktan çıkma",
                    relevance="query",
                    excerpt="Limited şirket müdürünün azli.",
                    grade="irrelevant",
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


@pytest.mark.asyncio
async def test_hydrate_keeps_relevant_excerpt_past_header_and_distributes_budget() -> None:
    from law_rag.crag import passes_prefilter

    long_body = (
        "**3. Hukuk Dairesi 2025/1 E., 2026/1 K.**\nMAHKEMESİ: Bölge Adliye Mahkemesi\n"
        + ("Taraflar ve usul bilgileri. " * 90)
        + "Uyuşmazlık güvence bedeli ve depozito alacağının iadesine ilişkindir."
    )

    class TwoFindingAnalyzer(AnalyzerWithGenericCategories):
        async def classify_risks(self, clauses, contract_type=None):
            return [
                RiskFinding(
                    id="finding-1",
                    category="deposit_forfeiture",
                    severity="high",
                    explanation="Depozito iade edilmez.",
                    recommendation="İade şartını yazın.",
                ),
                RiskFinding(
                    id="finding-2",
                    category="unlawful_entry",
                    severity="high",
                    explanation="İzinsiz giriş riski.",
                    recommendation="Bildirim şartı koyun.",
                ),
            ]

    class TwoFindingYargiClient:
        def __init__(self) -> None:
            self.fetched: list[str] = []

        async def search(self, query: str, category: str | None = None) -> list[YargiDecision]:
            if category == "deposit_forfeiture":
                return [
                    YargiDecision(source="Bedesten", title="D1", relevance=query, url="u://d1"),
                    YargiDecision(source="Bedesten", title="D2", relevance=query, url="u://d2"),
                ]
            return [
                YargiDecision(source="Bedesten", title="U1", relevance=query, url="u://u1"),
                YargiDecision(source="Bedesten", title="U2", relevance=query, url="u://u2"),
            ]

        async def fetch_decision_text(self, decision: YargiDecision) -> str | None:
            self.fetched.append(decision.title)
            if decision.title == "D1":
                return long_body
            return "Kiralanan konuta kiracının izni olmadan konut dokunulmazlığı ihlaliyle girilemez."

    yargi = TwoFindingYargiClient()
    report = await analyze_contract(
        file_name="lease.docx",
        file_type="docx",
        raw_text="MADDE 1 - Depozito.",
        contract_type="lease",
        analyzer=TwoFindingAnalyzer(),
        yargi_client=yargi,
        app_settings=Settings(crag_max_fetches_per_round=2, crag_max_rewrites=0),
    )

    assert yargi.fetched == ["D1", "U1"]
    titles = {d.title: d for d in report.related_decisions}
    assert "D1" in titles
    assert "U1" in titles
    assert passes_prefilter(titles["D1"], "deposit_forfeiture") is True
