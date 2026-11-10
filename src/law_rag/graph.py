"""LangGraph pipeline for contract analysis with a Corrective RAG retrieval loop.

segment_clauses -> classify_risks -> check_statutes -> score_contract
  -> build_legal_queries -> retrieve_yargi_decisions -> grade_decisions
       --(some finding needs a rewrite)--> rewrite_queries --> retrieve_yargi_decisions
       --(otherwise)--> select_decisions
  -> detect_missing_clauses -> suggest_rewrites -> compose_report

check_statutes runs the deterministic statutory limit checks, merges violations
into the findings, attaches curated statute references and applies the party
perspective; node bodies for the package-2 steps live in graph_steps.py.

Only findings whose status is "pending" are searched again, so a rewrite round
touches just the findings that still lack a relevant decision.
"""

from langgraph.graph import END, StateGraph

from .analyzer_base import (
    GRADE_FALLBACK_WARNING,
    REWRITE_FALLBACK_WARNING,
    ContractAnalyzer,
    drain_analyzer_warnings,
)
from .categories import category_from_finding, fallback_query, normalize_risk_findings
from .config import Settings, settings as default_settings
from .contract_types import normalize_contract_type, normalize_party
from .crag import (
    KEYWORD_ONLY_LIMITATION,
    MAX_RELATED_DECISIONS,
    MISSING_EXCERPT_LIMITATION,
    NO_RELEVANT_DECISION_LIMITATION,
    RETRIEVAL_FAILED_LIMITATION,
    apply_assessment,
    decision_key,
    hydrate_decisions,
    is_relevant_decision,
    keyword_grade,
    passes_prefilter,
    rewrite_feedback,
    select_related_decisions,
)
from .fake_analyzer import FakeContractAnalyzer
from .graph_steps import ExtraSteps, applicable, effective_contract_type
from .models import (
    ContractAnalysisState,
    ContractReport,
    DecisionAssessment,
    FindingRetrievalTrace,
    OcrInfo,
    RetrievalAttempt,
    RiskFinding,
    YargiDecision,
)
from .risk import calculate_risk_score, risk_level_for_score
from .text_utils import searchable
from .yargi_client import YargiClient

__all__ = [
    "MAX_RELATED_DECISIONS",
    "MISSING_EXCERPT_LIMITATION",
    "NO_RELEVANT_DECISION_LIMITATION",
    "analyze_contract",
    "build_contract_graph",
    "is_relevant_decision",
    "select_related_decisions",
]

NO_FINDINGS_LIMITATION = "No risk findings were detected by the MVP rules."


def _merge_limitations(existing: list[str], *new_groups: list[str]) -> list[str]:
    merged = list(existing)
    for group in new_groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return merged


def _query_key(query: str) -> str:
    return " ".join(searchable(query).split())


def build_contract_graph(
    analyzer: ContractAnalyzer,
    yargi_client: YargiClient,
    app_settings: Settings,
):
    """Compile the analysis graph for one analysis run (caches live per run)."""
    search_cache: dict[tuple[str, str], list[YargiDecision]] = {}
    text_cache: dict[str, str | None] = {}
    rule_based = FakeContractAnalyzer()

    def warnings() -> list[str]:
        return drain_analyzer_warnings(analyzer)

    extra = ExtraSteps(analyzer, app_settings, warnings)

    def findings_by_id(state: ContractAnalysisState) -> dict[str, RiskFinding]:
        return {finding.id: finding for finding in state.findings}

    async def segment_clauses(state: ContractAnalysisState) -> dict:
        clauses = await analyzer.segment_clauses(state.raw_text)
        return {"clauses": clauses, "limitations": _merge_limitations(state.limitations, warnings())}

    async def classify_risks(state: ContractAnalysisState) -> dict:
        if state.party is None:
            raw_findings = await analyzer.classify_risks(state.clauses, state.contract_type)
        else:
            raw_findings = await analyzer.classify_risks(
                state.clauses, state.contract_type, party=state.party
            )
        findings = normalize_risk_findings(raw_findings)
        return {"findings": findings, "limitations": _merge_limitations(state.limitations, warnings())}

    async def check_statutes(state: ContractAnalysisState) -> dict:
        update, limitations = await extra.check_statutes(state)
        return {**update, "limitations": _merge_limitations(state.limitations, limitations)}

    async def detect_missing_clauses(state: ContractAnalysisState) -> dict:
        update, limitations = await extra.detect_missing_clauses(state)
        return {**update, "limitations": _merge_limitations(state.limitations, limitations)}

    async def suggest_rewrites(state: ContractAnalysisState) -> dict:
        update, limitations = await extra.suggest_rewrites(state)
        return {**update, "limitations": _merge_limitations(state.limitations, limitations)}

    def score_contract(state: ContractAnalysisState) -> dict:
        # Findings that disadvantage only the other side do not count.
        risk_score = calculate_risk_score(applicable(state.findings))
        return {"risk_score": risk_score, "risk_level": risk_level_for_score(risk_score)}

    def type_kwargs(state: ContractAnalysisState) -> dict:
        # Passed only when known, so duck-typed analyzers without the parameter work.
        contract_type = effective_contract_type(state)[0]
        return {"contract_type": contract_type} if contract_type else {}

    async def build_legal_queries(state: ContractAnalysisState) -> dict:
        kwargs = type_kwargs(state)
        queries = (
            dict(await analyzer.build_legal_queries(state.findings, **kwargs)) if state.findings else {}
        )
        retrieval: dict[str, FindingRetrievalTrace] = {}
        for finding in state.findings:
            category = category_from_finding(finding)
            query = (queries.get(finding.id) or "").strip() or fallback_query(
                category, kwargs.get("contract_type")
            )
            queries[finding.id] = query
            retrieval[finding.id] = FindingRetrievalTrace(
                finding_id=finding.id,
                category=category,
                queries=[query],
            )
        return {
            "legal_queries": {finding.id: queries[finding.id] for finding in state.findings},
            "retrieval": retrieval,
            "limitations": _merge_limitations(state.limitations, warnings()),
        }

    async def retrieve_yargi_decisions(state: ContractAnalysisState) -> dict:
        retrieval = {key: trace.model_copy(deep=True) for key, trace in state.retrieval.items()}
        candidates = {key: list(items) for key, items in state.candidate_decisions.items()}
        limitations: list[str] = []
        for finding in state.findings:
            trace = retrieval.get(finding.id)
            if trace is None or trace.status != "pending":
                continue
            query = trace.queries[-1]
            attempt = len(trace.attempts) + 1
            cache_key = (_query_key(query), trace.category)
            try:
                if cache_key not in search_cache:
                    search_cache[cache_key] = await yargi_client.search(query, category=trace.category)
                found = search_cache[cache_key]
            except Exception as exc:
                trace.attempts.append(
                    RetrievalAttempt(attempt=attempt, query=query, error=exc.__class__.__name__)
                )
                trace.status = "failed"
                limitations.append(RETRIEVAL_FAILED_LIMITATION)
                continue
            existing = candidates.setdefault(finding.id, [])
            seen = {decision_key(decision) for decision in existing}
            new_count = 0
            for decision in found:
                key = decision_key(decision)
                if key in seen:
                    continue
                seen.add(key)
                existing.append(
                    decision.model_copy(
                        deep=True,
                        update={
                            "finding_id": finding.id,
                            "finding_category": trace.category,
                            "query": query,
                            "attempt": attempt,
                            "grade": None,
                            "grade_reason": None,
                            "graded_by": None,
                        },
                    )
                )
                new_count += 1
            trace.attempts.append(RetrievalAttempt(attempt=attempt, query=query, candidates=new_count))
            trace.status = "retrieved"
        return {
            "retrieval": retrieval,
            "candidate_decisions": candidates,
            "limitations": _merge_limitations(state.limitations, limitations),
        }

    async def grade_decisions(state: ContractAnalysisState) -> dict:
        retrieval = {key: trace.model_copy(deep=True) for key, trace in state.retrieval.items()}
        candidates = {
            key: [decision.model_copy(deep=True) for decision in items]
            for key, items in state.candidate_decisions.items()
        }
        use_llm = app_settings.crag_use_llm_grader
        fetch_budget = app_settings.crag_max_fetches_per_round
        limitations: list[str] = []
        for finding in state.findings:
            trace = retrieval.get(finding.id)
            if trace is None or trace.status != "retrieved":
                continue
            attempt = trace.attempts[-1]
            new = [
                decision
                for decision in candidates.get(finding.id, [])
                if decision.attempt == attempt.attempt and decision.grade is None
            ]
            fetch_budget -= await hydrate_decisions(
                new, yargi_client, budget=max(0, fetch_budget), cache=text_cache
            )
            if any(not decision.excerpt for decision in new):
                limitations.append(MISSING_EXCERPT_LIMITATION)

            # Keyword check is the cheap pre-filter: only decisions with text and at
            # least one category term are sent to the LLM grader.
            to_llm = [d for d in new if use_llm and passes_prefilter(d, trace.category)]
            to_llm_ids = {id(decision) for decision in to_llm}
            for decision in new:
                if id(decision) not in to_llm_ids:
                    apply_assessment(decision, keyword_grade(decision, trace.category))
            if to_llm:
                assessments, fell_back = await _grade_with_analyzer(finding, to_llm, trace.category)
                if fell_back:
                    limitations.append(GRADE_FALLBACK_WARNING)
                for decision, assessment in zip(to_llm, assessments):
                    apply_assessment(decision, assessment)

            attempt.relevant = sum(d.grade == "relevant" for d in new)
            attempt.ambiguous = sum(d.grade == "ambiguous" for d in new)
            attempt.irrelevant = sum(d.grade == "irrelevant" for d in new)
            attempt.grader = "llm" if any(d.graded_by == "llm" for d in new) else "keyword"
            if attempt.relevant:
                trace.status = "relevant"
            elif trace.rewrites_used < app_settings.crag_max_rewrites:
                trace.status = "needs_rewrite"
            else:
                trace.status = "exhausted"
        return {
            "retrieval": retrieval,
            "candidate_decisions": candidates,
            "limitations": _merge_limitations(state.limitations, limitations, warnings()),
        }

    async def _grade_with_analyzer(
        finding: RiskFinding,
        decisions: list[YargiDecision],
        category: str,
    ) -> tuple[list[DecisionAssessment], bool]:
        """Grade with the analyzer; on error or malformed output use the keyword grader."""
        try:
            assessments = list(await analyzer.grade_decisions(finding, decisions))
            if len(assessments) == len(decisions):
                return assessments, False
        except Exception:
            pass
        return [keyword_grade(decision, category) for decision in decisions], True

    async def rewrite_queries(state: ContractAnalysisState) -> dict:
        retrieval = {key: trace.model_copy(deep=True) for key, trace in state.retrieval.items()}
        by_id = findings_by_id(state)
        kwargs = type_kwargs(state)
        limitations: list[str] = []
        for finding_id, trace in retrieval.items():
            if trace.status != "needs_rewrite":
                continue
            finding = by_id[finding_id]
            feedback = rewrite_feedback(trace, state.candidate_decisions.get(finding_id, []))
            try:
                query = await analyzer.rewrite_query(finding, list(trace.queries), feedback, **kwargs)
            except Exception:
                limitations.append(REWRITE_FALLBACK_WARNING)
                query = await rule_based.rewrite_query(finding, list(trace.queries), feedback, **kwargs)
            query = (query or "").strip()
            tried = {_query_key(previous) for previous in trace.queries}
            if not query or _query_key(query) in tried:
                trace.status = "exhausted"
                continue
            trace.queries.append(query)
            trace.status = "pending"
        return {
            "retrieval": retrieval,
            "limitations": _merge_limitations(state.limitations, limitations, warnings()),
        }

    def select_decisions(state: ContractAnalysisState) -> dict:
        ordered = {
            finding.id: state.candidate_decisions.get(finding.id, [])
            for finding in state.findings
            if finding.id in state.retrieval
        }
        selected, limitations = select_related_decisions(
            ordered,
            total_limit=min(app_settings.yargi_max_total_decisions, MAX_RELATED_DECISIONS),
        )
        if state.findings and not app_settings.crag_use_llm_grader:
            limitations.append(KEYWORD_ONLY_LIMITATION)
        return {
            "related_decisions": selected,
            "limitations": _merge_limitations(state.limitations, limitations),
        }

    async def compose_report(state: ContractAnalysisState) -> dict:
        limitations = list(state.limitations)
        if not state.findings:
            limitations.append(NO_FINDINGS_LIMITATION)
        recommended_actions = list(
            dict.fromkeys(finding.recommendation for finding in applicable(state.findings))
        )
        summary = await analyzer.summarize_contract(state.raw_text, state.contract_type)
        limitations = _merge_limitations(limitations, warnings())
        report = ContractReport(
            contract_summary=summary,
            clauses=state.clauses,
            findings=state.findings,
            risk_score=state.risk_score,
            risk_level=state.risk_level,
            contract_type=state.contract_type,
            party=state.party,
            recommended_actions=recommended_actions,
            statutory_checks=state.statutory_checks,
            missing_clauses=state.missing_clauses,
            rewrites=state.rewrites,
            related_decisions=state.related_decisions,
            retrieval_trace=[
                state.retrieval[finding.id] for finding in state.findings if finding.id in state.retrieval
            ],
            ocr=state.ocr,
            limitations=limitations,
        )
        return {
            "contract_summary": summary,
            "recommended_actions": recommended_actions,
            "limitations": limitations,
            "report": report,
        }

    def after_grading(state: ContractAnalysisState) -> str:
        if any(trace.status == "needs_rewrite" for trace in state.retrieval.values()):
            return "rewrite_queries"
        return "select_decisions"

    def after_rewrite(state: ContractAnalysisState) -> str:
        if any(trace.status == "pending" for trace in state.retrieval.values()):
            return "retrieve_yargi_decisions"
        return "select_decisions"

    workflow = StateGraph(ContractAnalysisState)
    workflow.add_node("segment_clauses", segment_clauses)
    workflow.add_node("classify_risks", classify_risks)
    workflow.add_node("check_statutes", check_statutes)
    workflow.add_node("score_contract", score_contract)
    workflow.add_node("build_legal_queries", build_legal_queries)
    workflow.add_node("retrieve_yargi_decisions", retrieve_yargi_decisions)
    workflow.add_node("grade_decisions", grade_decisions)
    workflow.add_node("rewrite_queries", rewrite_queries)
    workflow.add_node("select_decisions", select_decisions)
    workflow.add_node("detect_missing_clauses", detect_missing_clauses)
    workflow.add_node("suggest_rewrites", suggest_rewrites)
    workflow.add_node("compose_report", compose_report)

    workflow.set_entry_point("segment_clauses")
    workflow.add_edge("segment_clauses", "classify_risks")
    workflow.add_edge("classify_risks", "check_statutes")
    workflow.add_edge("check_statutes", "score_contract")
    workflow.add_edge("score_contract", "build_legal_queries")
    workflow.add_edge("build_legal_queries", "retrieve_yargi_decisions")
    workflow.add_edge("retrieve_yargi_decisions", "grade_decisions")
    workflow.add_conditional_edges(
        "grade_decisions",
        after_grading,
        {"rewrite_queries": "rewrite_queries", "select_decisions": "select_decisions"},
    )
    workflow.add_conditional_edges(
        "rewrite_queries",
        after_rewrite,
        {"retrieve_yargi_decisions": "retrieve_yargi_decisions", "select_decisions": "select_decisions"},
    )
    workflow.add_edge("select_decisions", "detect_missing_clauses")
    workflow.add_edge("detect_missing_clauses", "suggest_rewrites")
    workflow.add_edge("suggest_rewrites", "compose_report")
    workflow.add_edge("compose_report", END)
    return workflow.compile()


async def analyze_contract(
    *,
    file_name: str,
    file_type: str,
    raw_text: str,
    analyzer: ContractAnalyzer,
    yargi_client: YargiClient,
    contract_type: str | None = None,
    party: str | None = None,
    app_settings: Settings | None = None,
    ocr: OcrInfo | None = None,
    initial_limitations: list[str] | None = None,
) -> ContractReport:
    """Run the analysis graph.

    `contract_type` is normalised to lease / service / employment / other (an
    unrecognised value is passed through unchanged). `party` is the user's role
    for that type (tenant/landlord, client/provider, employee/employer, Turkish
    aliases accepted); unknown or missing means a neutral analysis. `ocr` and
    `initial_limitations` come from document loading (OCR) and are carried into
    the report.
    """
    run_settings = app_settings or default_settings
    graph = build_contract_graph(analyzer, yargi_client, run_settings)
    normalized_type, normalized_party = normalize_party(
        normalize_contract_type(contract_type), party
    )
    initial_state = ContractAnalysisState(
        file_name=file_name,
        file_type=file_type,
        contract_type=normalized_type,
        party=normalized_party,
        raw_text=raw_text,
        ocr=ocr,
        limitations=list(initial_limitations or []),
    )
    # Linear nodes + three nodes per CRAG round, with headroom.
    recursion_limit = 25 + 3 * (run_settings.crag_max_rewrites + 1)
    result = await graph.ainvoke(initial_state, config={"recursion_limit": recursion_limit})
    report = result.get("report") if isinstance(result, dict) else result.report
    if report is None:
        raise RuntimeError("Contract analysis completed without a report.")
    return report
