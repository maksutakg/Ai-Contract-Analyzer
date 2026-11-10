from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "critical"]
Severity = Literal["low", "medium", "high", "critical"]
DecisionGrade = Literal["relevant", "ambiguous", "irrelevant"]
GraderKind = Literal["llm", "keyword"]
# pending: a query is waiting to be searched; retrieved: candidates await grading;
# relevant: at least one relevant decision; needs_rewrite: no relevant decision and
# rewrites left; exhausted: no relevant decision and no (new) query left;
# failed: the Yargı search itself raised.
RetrievalStatus = Literal["pending", "retrieved", "relevant", "needs_rewrite", "exhausted", "failed"]
# llm: the Gemini classifier; rule_based: the deterministic analyzer (offline or
# as a fallback); statutory_rule: a violated statutory limit check (code, not LLM).
FindingSource = Literal["llm", "rule_based", "statutory_rule"]
CheckStatus = Literal["violation", "ok", "needs_review", "not_applicable"]
Importance = Literal["low", "medium", "high"]
ProducedBy = Literal["llm", "rule_based"]


class Clause(BaseModel):
    id: str
    title: str | None = None
    text: str


class LegalReference(BaseModel):
    """A curated, verified statute provision. Never produced by the LLM."""

    law_name: str
    law_number: str
    article: str
    summary: str
    url: str
    article_text: str | None = None


class RiskFinding(BaseModel):
    id: str
    category: str
    severity: Severity
    explanation: str
    recommendation: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    clause_id: str | None = None
    # Party role id the clause works against ("tenant", "employer", ...), "both",
    # or None when unknown. See contract_types.py for the role ids.
    disadvantaged_party: str | None = None
    # False when a party was given and the finding disadvantages only the other
    # side: kept in the report but excluded from the risk score.
    applies_to_user: bool = True
    detected_by: FindingSource | None = None
    statutory_check_id: str | None = None
    legal_references: list[LegalReference] = Field(default_factory=list)


class ExtractedFact(BaseModel):
    """One fact pulled out of the contract for the statutory limit checks."""

    name: str
    value: float | str | bool
    clause_id: str | None = None
    extracted_by: ProducedBy = "rule_based"


class StatutoryCheck(BaseModel):
    rule_id: str
    title: str
    status: CheckStatus
    clause_id: str | None = None
    extracted_value: str | None = None
    limit: str | None = None
    explanation: str
    legal_basis: LegalReference
    finding_id: str | None = None
    extracted_by: ProducedBy | None = None


class TopicPresence(BaseModel):
    """Analyzer verdict on one checklist topic."""

    present: bool
    detected_by: ProducedBy = "rule_based"


class MissingClause(BaseModel):
    topic: str
    title: str
    importance: Importance
    explanation: str
    suggested_clause: str
    detected_by: ProducedBy = "rule_based"


class ClauseRewrite(BaseModel):
    clause_id: str
    finding_ids: list[str] = Field(default_factory=list)
    original_text: str
    suggested_text: str
    rationale: str
    generated_by: ProducedBy = "rule_based"


class DecisionAssessment(BaseModel):
    """One grader verdict for one candidate decision."""

    grade: DecisionGrade
    reason: str
    graded_by: GraderKind = "keyword"


class YargiDecision(BaseModel):
    finding_id: str | None = None
    finding_category: str | None = None
    source: str
    title: str
    relevance: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    decision_date: str | None = None
    decision_number: str | None = None
    excerpt: str | None = None
    url: str | None = None
    # CRAG bookkeeping: which query/attempt surfaced the decision and how it was graded.
    query: str | None = None
    attempt: int | None = None
    grade: DecisionGrade | None = None
    grade_reason: str | None = None
    graded_by: GraderKind | None = None


class RetrievalAttempt(BaseModel):
    attempt: int
    query: str
    candidates: int = 0
    relevant: int = 0
    ambiguous: int = 0
    irrelevant: int = 0
    grader: GraderKind | None = None
    error: str | None = None


class FindingRetrievalTrace(BaseModel):
    """Per-finding CRAG history: queries tried in order and grade counts per attempt."""

    finding_id: str
    category: str
    queries: list[str] = Field(default_factory=list)
    attempts: list[RetrievalAttempt] = Field(default_factory=list)
    status: RetrievalStatus = "pending"

    @property
    def rewrites_used(self) -> int:
        return max(0, len(self.queries) - 1)


FileType = Literal["pdf", "docx", "image"]
# image_upload: a jpg/png was uploaded; thin_text_layer: a PDF whose text layer
# is missing or too thin to be a contract (see document_loader.py).
OcrReason = Literal["image_upload", "thin_text_layer"]


class OcrInfo(BaseModel):
    """Recorded when the contract text was transcribed from page images."""

    used: bool = True
    reason: OcrReason
    pages: int = Field(ge=0)
    failed_pages: list[int] = Field(default_factory=list)
    engine: Literal["gemini", "fake"]
    model: str | None = None


class ContractReport(BaseModel):
    contract_summary: str
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    # Normalised contract type (lease, service, employment, other) or the raw value
    # when unrecognised; party is the user's role id or None (neutral analysis).
    contract_type: str | None = None
    party: str | None = None
    clauses: list[Clause] = Field(default_factory=list)
    findings: list[RiskFinding] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    statutory_checks: list[StatutoryCheck] = Field(default_factory=list)
    missing_clauses: list[MissingClause] = Field(default_factory=list)
    rewrites: list[ClauseRewrite] = Field(default_factory=list)
    related_decisions: list[YargiDecision] = Field(default_factory=list)
    retrieval_trace: list[FindingRetrievalTrace] = Field(default_factory=list)
    # Set when the text came from OCR; None for a PDF text layer or DOCX.
    ocr: OcrInfo | None = None
    limitations: list[str] = Field(default_factory=list)


class ContractAnalysisState(BaseModel):
    file_name: str
    file_type: FileType
    ocr: OcrInfo | None = None
    contract_type: str | None = None
    party: str | None = None
    raw_text: str = ""
    contract_summary: str = ""
    clauses: list[Clause] = Field(default_factory=list)
    findings: list[RiskFinding] = Field(default_factory=list)
    statutory_checks: list[StatutoryCheck] = Field(default_factory=list)
    missing_clauses: list[MissingClause] = Field(default_factory=list)
    rewrites: list[ClauseRewrite] = Field(default_factory=list)
    # Initial query per finding id, produced once by build_legal_queries.
    legal_queries: dict[str, str] = Field(default_factory=dict)
    # CRAG loop state keyed by finding id (query history, attempts, status).
    retrieval: dict[str, FindingRetrievalTrace] = Field(default_factory=dict)
    # Every candidate decision seen per finding id, graded once retrieved.
    candidate_decisions: dict[str, list[YargiDecision]] = Field(default_factory=dict)
    related_decisions: list[YargiDecision] = Field(default_factory=list)
    risk_score: int = 0
    risk_level: RiskLevel = "low"
    recommended_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    report: ContractReport | None = None
