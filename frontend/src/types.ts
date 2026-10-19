// Mirrors src/law_rag/models.py; the fixture test fails if the two drift apart.
export type Severity = "low" | "medium" | "high" | "critical";
export type ContractType = "service" | "lease";

export interface Clause {
  id: string;
  title: string | null;
  text: string;
}

export interface RiskFinding {
  id: string;
  category: string;
  severity: Severity;
  explanation: string;
  recommendation: string;
  confidence: number;
  clause_id: string | null;
}

export interface YargiDecision {
  finding_id: string | null;
  finding_category: string | null;
  source: string;
  court: string | null;
  title: string;
  relevance: string;
  confidence: number;
  decision_date: string | null;
  decision_number: string | null;
  excerpt: string | null;
  url: string | null;
}

export interface ContractReport {
  contract_summary: string;
  risk_score: number;
  risk_level: Severity;
  clauses: Clause[];
  findings: RiskFinding[];
  recommended_actions: string[];
  related_decisions: YargiDecision[];
  limitations: string[];
  llm_engine: string;
  yargi_source: string;
}
