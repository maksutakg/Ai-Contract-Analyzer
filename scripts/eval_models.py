from pydantic import BaseModel, Field

from law_rag.models import DecisionGrade, RiskLevel, Severity


class ExpectedFinding(BaseModel):
    clause_id: str
    category: str
    severity: Severity | None = None
    disadvantaged_party: str | None = None
    statutory: bool = False


class GradedDecisionExample(BaseModel):
    finding_category: str
    finding_explanation: str
    decision_title: str
    decision_excerpt: str
    expected_grade: DecisionGrade


class ChatEvalQuestion(BaseModel):
    question: str
    covered: bool
    relevant_chunk_ids: list[str] = Field(default_factory=list)


class AnnotatedContract(BaseModel):
    contract_id: str
    contract_type: str
    party: str | None = None
    expected_risk_level: RiskLevel | None = None
    raw_text: str
    expected_findings: list[ExpectedFinding] = Field(default_factory=list)
    expected_missing_topics: list[str] = Field(default_factory=list)
    decision_examples: list[GradedDecisionExample] = Field(default_factory=list)
    chat_questions: list[ChatEvalQuestion] = Field(default_factory=list)


class EvalDataset(BaseModel):
    version: str = "1.0"
    contracts: list[AnnotatedContract]

