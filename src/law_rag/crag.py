"""Corrective RAG helpers: keyword grading, hydration, selection and feedback.

The graph nodes in graph.py orchestrate the loop; this module holds the pure(ish)
pieces so they can be reused by the analyzers and by the evaluation harness.
"""

from collections.abc import Iterable

from .categories import relevance_terms
from .models import DecisionAssessment, FindingRetrievalTrace, YargiDecision
from .text_utils import searchable

MAX_RELATED_DECISIONS = 5
MAX_RELATED_DECISIONS_PER_FINDING = 1
HYDRATED_EXCERPT_CHARS = 1200

NO_RELEVANT_DECISION_LIMITATION = "No sufficiently relevant Yargi MCP decision was found for some findings."
AMBIGUOUS_DECISION_LIMITATION = (
    "Some findings only had ambiguously relevant Yargi MCP decisions; they are marked as ambiguous."
)
MISSING_EXCERPT_LIMITATION = (
    "Some Yargi MCP results had no text (fetch budget exhausted or fetch failed) and were graded irrelevant."
)
RETRIEVAL_FAILED_LIMITATION = "Yargi MCP retrieval failed for some queries."
DECISION_CAP_LIMITATION = "Related decisions were capped at {limit}; later findings have none listed."
KEYWORD_ONLY_LIMITATION ="Decision relevance was graded with keyword matching only (LLM grader disabled)."

NO_TEXT_REASON = "Karar metni veya özeti alınamadığı için değerlendirilemedi."


def decision_key(decision: YargiDecision) -> str:
    return decision.url or decision.decision_number or f"{decision.source}:{decision.title}"


def decision_text(decision: YargiDecision) -> str:
    return " ".join(part for part in [decision.title, decision.excerpt] if part)


def matched_terms(decision: YargiDecision, category: str | None) -> list[str]:
    haystack = searchable(decision_text(decision))
    return [term for term in relevance_terms(category) if searchable(term) in haystack]


def keyword_grade(decision: YargiDecision, category: str | None) -> DecisionAssessment:
    """Deterministic grader: >=2 category terms relevant, 1 ambiguous, 0 irrelevant."""
    if not decision.excerpt:
        return DecisionAssessment(grade="irrelevant", reason=NO_TEXT_REASON, graded_by="keyword")
    terms = relevance_terms(category)
    if not terms:
        return DecisionAssessment(
            grade="ambiguous",
            reason="Bu kategori için anahtar terim tanımlı olmadığından ilgi düzeyi belirsiz.",
            graded_by="keyword",
        )
    hits = matched_terms(decision, category)
    if len(hits) >= min(2, len(terms)):
        return DecisionAssessment(
            grade="relevant",
            reason=f"Kararda bulguya ait anahtar terimler geçiyor: {', '.join(hits[:4])}.",
            graded_by="keyword",
        )
    if hits:
        return DecisionAssessment(
            grade="ambiguous",
            reason=f"Kararda yalnızca bir anahtar terim geçiyor: {hits[0]}.",
            graded_by="keyword",
        )
    return DecisionAssessment(
        grade="irrelevant",
        reason="Kararda bulgunun kategorisine ait anahtar terim bulunamadı.",
        graded_by="keyword",
    )


def passes_prefilter(decision: YargiDecision, category: str | None) -> bool:
    """Cheap pre-filter before LLM grading: needs text and at least one category term."""
    if not decision.excerpt:
        return False
    if not relevance_terms(category):
        return True
    return bool(matched_terms(decision, category))


def is_relevant_decision(decision: YargiDecision) -> bool:
    """Backward-compatible keyword relevance check on a decision's own category."""
    category = decision.finding_category
    if not category or not relevance_terms(category):
        return True
    return keyword_grade(decision, category).grade == "relevant"


def apply_assessment(decision: YargiDecision, assessment: DecisionAssessment) -> None:
    decision.grade = assessment.grade
    decision.grade_reason = assessment.reason
    decision.graded_by = assessment.graded_by


async def hydrate_decisions(
    decisions: Iterable[YargiDecision],
    yargi_client: object,
    *,
    budget: int,
    cache: dict[str, str | None],
) -> int:
    """Fill missing excerpts via `fetch_decision_text`, at most `budget` network fetches.

    Returns the number of fetches performed. Results (including failures) are
    cached by decision key so a decision shared by findings is fetched once.
    """
    fetch = getattr(yargi_client, "fetch_decision_text", None)
    if fetch is None:
        return 0
    fetches = 0
    for decision in decisions:
        if decision.excerpt:
            continue
        key = decision_key(decision)
        if key not in cache:
            if fetches >= budget:
                continue
            fetches += 1
            try:
                cache[key] = await fetch(decision)
            except Exception:
                cache[key] = None
        text = cache[key]
        if text:
            decision.excerpt = text[:HYDRATED_EXCERPT_CHARS]
    return fetches


def rewrite_feedback(trace: FindingRetrievalTrace, decisions: list[YargiDecision]) -> str:
    """Turkish explanation of why the latest query failed, for the rewrite prompt."""
    if not trace.attempts:
        return "Henüz arama yapılmadı."
    last = trace.attempts[-1]
    if last.candidates == 0:
        return f"'{last.query}' sorgusu hiç karar döndürmedi; sorgu muhtemelen fazla dar veya çok fazla tırnaklı ifade içeriyor."
    reasons = [
        f"- {decision.title}: {decision.grade} ({decision.grade_reason})"
        for decision in decisions
        if decision.attempt == last.attempt
    ][:5]
    return (
        f"'{last.query}' sorgusu {last.candidates} karar döndürdü ancak hiçbiri bulguyla "
        f"yeterince ilgili değil (ilgili: {last.relevant}, belirsiz: {last.ambiguous}, "
        f"ilgisiz: {last.irrelevant}).\n" + "\n".join(reasons)
    )


def select_related_decisions(
    candidates_by_finding: dict[str, list[YargiDecision]],
    *,
    total_limit: int = MAX_RELATED_DECISIONS,
    per_finding: int = MAX_RELATED_DECISIONS_PER_FINDING,
) -> tuple[list[YargiDecision], list[str]]:
    """Pick graded decisions for the report.

    Relevant decisions are preferred; a finding with no relevant decision falls
    back to its best ambiguous one (still labelled ambiguous). A decision is not
    reported twice for different findings.
    """
    selected: list[YargiDecision] = []
    limitations: list[str] = []
    used_keys: set[str] = set()
    limit = min(total_limit, MAX_RELATED_DECISIONS)

    def note(limitation: str) -> None:
        if limitation not in limitations:
            limitations.append(limitation)

    for decisions in candidates_by_finding.values():
        if len(selected) >= limit:
            note(DECISION_CAP_LIMITATION.format(limit=limit))
            break
        relevant = [decision for decision in decisions if decision.grade == "relevant"]
        chosen = relevant
        if not relevant:
            note(NO_RELEVANT_DECISION_LIMITATION)
            chosen = [decision for decision in decisions if decision.grade == "ambiguous"]
            if chosen:
                note(AMBIGUOUS_DECISION_LIMITATION)
        # A decision already listed for an earlier finding is not repeated.
        chosen = [decision for decision in chosen if decision_key(decision) not in used_keys]
        for decision in chosen[:per_finding]:
            if len(selected) >= limit:
                break
            used_keys.add(decision_key(decision))
            selected.append(decision)
    return selected, limitations
