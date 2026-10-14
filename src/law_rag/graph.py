import unicodedata
from langgraph.graph import END, StateGraph

from .config import Settings, settings
from .llm import ContractAnalyzer, normalize_risk_findings
from .models import ContractAnalysisState, ContractReport, YargiDecision
from .risk import calculate_risk_score, risk_level_for_score
from .yargi_client import YargiClient


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


MAX_RELATED_DECISIONS = 5
MAX_RELATED_DECISIONS_PER_FINDING = 1
MISSING_EXCERPT_LIMITATION = "Some Yargi MCP results had no excerpt and were deprioritized."
NO_RELEVANT_DECISION_LIMITATION = "No sufficiently relevant Yargi MCP decision was found for some findings."

RELEVANCE_TERMS_BY_CATEGORY = {
    "data_protection": [
        "kvkk",
        "veri işleyen",
        "veri sorumlusu",
        "kişisel veri",
        "kişisel verilerin korunması",
        "kisisel veri",
        "veri güvenliği",
        "veri ihlali",
        "aydinlatma yukumlulugu",
        "açık rıza",
    ],
    "intellectual_property": [
        "fikri mülkiyet",
        "eser",
        "yazılım",
        "hak devri",
        "lisans",
        "telif hakkı",
        "fsek",
        "fikri haklar",
        "hakların devri",
        "kaynak kod",
        "lisans sözleşmesi",
    ],
    "termination": [
        "fesih",
        "haklı neden",
        "derhal fesih",
        "sözleşmenin sona ermesi",
        "fesih hakkı",
        "sözleşmeyi sona erdirme",
        "hakli nedenle fesih",
        "ihbar süresi",
        "bildirimli fesih",
    ],
    "payment_interest": [
        "gecikme faizi",
        "temerrüt",
        "ticari faiz",
        "gecikme faiz oranı",
        "temerrut faizi",
        "yasal faiz",
        "faiz istemi",
    ],
    "penalty_clause": [
        "cezai şart",
        "tbk",
        "türk borçlar kanunu",
        "indirim",
        "ceza koşulu",
        "cezai sart",
        "muacceliyet",
        "fahiş ceza",
        "cezanın indirilmesi",
    ],
    "force_majeure": [
        "mücbir sebep",
        "ifa imkansızlığı",
        "beklenmeyen hal",
        "mucbir sebep",
        "beklenmeyen durum",
        "aşırı ifa güçlüğü",
        "sözleşmenin uyarlanması",
    ],
    "deposit_forfeiture": [
        "depozito",
        "güvence bedeli",
        "iade edilmez",
        "iade edilmemesi",
        "kesinti",
        "teminat",
    ],
    "rent_increase": [
        "kira artışı",
        "yasal sınır",
        "artırım oranı",
        "tüfe",
        "kira bedeli",
        "kira tespit",
    ],
    "jurisdiction": [
        "yetkili mahkeme",
        "yetki sözleşmesi",
        "yetki itirazı",
        "tahkim şartı",
        "istac",
        "uyuşmazlık çözümü",
    ],
    "eviction_undertaking": [
        "tahliye taahhüdü",
        "tahliye taahhütnamesi",
        "tahliye davası",
        "tahliye tarihi",
    ],
}


def is_relevant_decision(decision: YargiDecision) -> bool:
    category = decision.finding_category
    if not category:
        return True
    terms = RELEVANCE_TERMS_BY_CATEGORY.get(category)
    if not terms:
        return True
    raw_haystack = " ".join(
        part
        for part in [decision.title, decision.excerpt]
        if part
    )
    haystack = _normalize_text(raw_haystack)
    matches = sum(1 for term in terms if _normalize_text(term) in haystack)
    return matches >= min(2, len(terms))


def select_related_decisions(
    decisions_by_finding: dict[str, list[YargiDecision]],
    app_settings: Settings = settings,
) -> tuple[list[YargiDecision], list[str]]:
    selected: list[YargiDecision] = []
    limitations: list[str] = []
    saw_missing_excerpt = False
    total_limit = min(app_settings.yargi_max_total_decisions, MAX_RELATED_DECISIONS)

    for decisions in decisions_by_finding.values():
        if not decisions or len(selected) >= total_limit:
            break
        relevant_decisions = [
            decision
            for decision in decisions
            if is_relevant_decision(decision)
        ]
        if not relevant_decisions:
            if NO_RELEVANT_DECISION_LIMITATION not in limitations:
                limitations.append(NO_RELEVANT_DECISION_LIMITATION)
            continue
        saw_missing_excerpt = saw_missing_excerpt or any(not decision.excerpt for decision in decisions)
        ranked = sorted(relevant_decisions, key=lambda decision: 0 if decision.excerpt else 1)
        selected.extend(ranked[:MAX_RELATED_DECISIONS_PER_FINDING])
        selected = selected[:total_limit]

    if saw_missing_excerpt:
        limitations.append(MISSING_EXCERPT_LIMITATION)
    return selected, limitations


async def hydrate_selected_decisions(
    decisions: list[YargiDecision],
    yargi_client: YargiClient,
) -> None:
    fetch_decision_text = getattr(yargi_client, "fetch_decision_text", None)
    if fetch_decision_text is None:
        return
    for decision in decisions:
        if decision.excerpt:
            continue
        document_text = await fetch_decision_text(decision)
        if document_text:
            decision.excerpt = document_text[:1200]


def filter_hydrated_decisions(
    decisions: list[YargiDecision],
) -> tuple[list[YargiDecision], list[str]]:
    relevant = [decision for decision in decisions if is_relevant_decision(decision)]
    if len(relevant) == len(decisions):
        return relevant, []
    return relevant, [NO_RELEVANT_DECISION_LIMITATION]


async def analyze_contract(
    *,
    file_name: str,
    file_type: str,
    raw_text: str,
    analyzer: ContractAnalyzer,
    yargi_client: YargiClient,
    contract_type: str | None = None,
    app_settings: Settings = settings,
) -> ContractReport:
    def decision_key(decision) -> str:
        return decision.url or decision.decision_number or f"{decision.source}:{decision.title}"

    async def segment_clauses(state: ContractAnalysisState) -> dict:
        clauses = await analyzer.segment_clauses(state.raw_text)
        return {"clauses": clauses}

    async def classify_risks(state: ContractAnalysisState) -> dict:
        findings = normalize_risk_findings(
            await analyzer.classify_risks(state.clauses, state.contract_type)
        )
        return {"findings": findings}

    def score_contract(state: ContractAnalysisState) -> dict:
        risk_score = calculate_risk_score(state.findings)
        return {
            "risk_score": risk_score,
            "risk_level": risk_level_for_score(risk_score),
        }

    async def build_legal_queries(state: ContractAnalysisState) -> dict:
        queries = {
            finding.id: await analyzer.build_legal_queries([finding])
            for finding in state.findings
        }
        return {"legal_queries": queries}

    async def retrieve_yargi_decisions(state: ContractAnalysisState) -> dict:
        decisions_by_finding: dict[str, list[YargiDecision]] = {}
        seen_decisions: set[str] = set()
        limitations = list(state.limitations)
        try:
            for finding in state.findings:
                for query in state.legal_queries.get(finding.id, []):
                    found_decisions = await yargi_client.search(query, category=finding.category)
                    for decision in found_decisions:
                        decision.finding_id = finding.id
                        decision.finding_category = finding.category
                        key = decision_key(decision)
                        if key in seen_decisions:
                            continue
                        seen_decisions.add(key)
                        decisions_by_finding.setdefault(finding.id, []).append(decision)
        except Exception:
            limitations.append("Yargi MCP retrieval failed.")
        decisions, selection_limitations = select_related_decisions(decisions_by_finding, app_settings)
        if app_settings.yargi_fetch_documents:
            await hydrate_selected_decisions(decisions, yargi_client)
        decisions, hydration_limitations = filter_hydrated_decisions(decisions)
        limitations.extend(
            limitation
            for limitation in [*selection_limitations, *hydration_limitations]
            if limitation not in limitations
        )
        return {"related_decisions": decisions, "limitations": limitations}

    async def compose_report(state: ContractAnalysisState) -> dict:
        limitations = list(state.limitations)
        if not state.findings:
            limitations.append("No risk findings were detected by the MVP rules.")

        recommended_actions = [
            finding.recommendation
            for finding in state.findings
        ]

        summary = await analyzer.summarize_contract(state.raw_text, state.contract_type)
        report = ContractReport(
            contract_summary=summary,
            clauses=state.clauses,
            findings=state.findings,
            risk_score=state.risk_score,
            risk_level=state.risk_level,
            recommended_actions=recommended_actions,
            related_decisions=state.related_decisions,
            limitations=limitations,
        )
        return {
            "contract_summary": summary,
            "recommended_actions": recommended_actions,
            "limitations": limitations,
            "report": report,
        }

    workflow = StateGraph(ContractAnalysisState)
    workflow.add_node("segment_clauses", segment_clauses)
    workflow.add_node("classify_risks", classify_risks)
    workflow.add_node("score_contract", score_contract)
    workflow.add_node("build_legal_queries", build_legal_queries)
    workflow.add_node("retrieve_yargi_decisions", retrieve_yargi_decisions)
    workflow.add_node("compose_report", compose_report)

    workflow.set_entry_point("segment_clauses")
    workflow.add_edge("segment_clauses", "classify_risks")
    workflow.add_edge("classify_risks", "score_contract")
    workflow.add_edge("score_contract", "build_legal_queries")
    workflow.add_edge("build_legal_queries", "retrieve_yargi_decisions")
    workflow.add_edge("retrieve_yargi_decisions", "compose_report")
    workflow.add_edge("compose_report", END)

    graph = workflow.compile()
    initial_state = ContractAnalysisState(
        file_name=file_name,
        file_type=file_type,
        contract_type=contract_type,
        raw_text=raw_text,
    )
    result = await graph.ainvoke(initial_state)
    report = result.get("report") if isinstance(result, dict) else result.report
    if report is None:
        raise RuntimeError("Contract analysis completed without a report.")
    return report
