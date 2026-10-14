from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "critical"]
Severity = Literal["low", "medium", "high", "critical"]
ContractType = Literal["service", "lease"]


class Clause(BaseModel):
    id: str
    title: str | None = None
    text: str


class RiskFinding(BaseModel):
    id: str
    category: str
    severity: Severity
    explanation: str
    recommendation: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    clause_id: str | None = None


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


class ContractReport(BaseModel):
    contract_summary: str
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    clauses: list[Clause] = Field(default_factory=list)
    findings: list[RiskFinding] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    related_decisions: list[YargiDecision] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    llm_engine: str = "rules"
    yargi_source: str = "fake"


class ContractAnalysisState(BaseModel):
    file_name: str
    file_type: Literal["pdf", "docx"]
    contract_type: str | None = None
    raw_text: str = ""
    contract_summary: str = ""
    clauses: list[Clause] = Field(default_factory=list)
    findings: list[RiskFinding] = Field(default_factory=list)
    legal_queries: dict[str, list[str]] = Field(default_factory=dict)
    related_decisions: list[YargiDecision] = Field(default_factory=list)
    risk_score: int = 0
    risk_level: RiskLevel = "low"
    recommended_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    report: ContractReport | None = None
