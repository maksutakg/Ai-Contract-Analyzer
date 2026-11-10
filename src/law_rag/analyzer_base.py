"""Analyzer protocol and the warning side-channel shared by all analyzers.

Warnings mechanism: an analyzer that degrades (for example the Gemini call
fails and the rule-based analyzer is used instead) records an English warning
string with `_warn()`. The graph calls `drain_warnings()` after every analyzer
call and moves the warnings into the report's `limitations`. Warnings belong to
the analysis that triggered them, so an analyzer instance must not be shared by
concurrent analyses (the API creates one per request).
"""

from typing import Protocol, runtime_checkable

from .models import (
    Clause,
    ClauseRewrite,
    DecisionAssessment,
    ExtractedFact,
    RiskFinding,
    TopicPresence,
    YargiDecision,
)

SUMMARY_FALLBACK_WARNING = "LLM contract summary failed; a rule-based excerpt was used instead."
CLASSIFY_FALLBACK_WARNING = (
    "LLM risk classification failed for some clause batches; "
    "the rule-based analyzer was used for those clauses instead."
)
QUERY_FALLBACK_WARNING = (
    "LLM legal query generation failed for some findings; rule-based queries were used instead."
)
GRADE_FALLBACK_WARNING = (
    "LLM relevance grading failed for some findings; the keyword grader was used instead."
)
REWRITE_FALLBACK_WARNING = (
    "LLM query rewriting failed for some findings; rule-based rewriting was used instead."
)
FACTS_FALLBACK_WARNING = (
    "LLM fact extraction for the statutory checks failed for some clauses; "
    "regex extraction was used instead."
)
MISSING_CLAUSES_FALLBACK_WARNING = (
    "LLM missing-clause detection failed or was incomplete; keyword matching was used for some topics."
)
CLAUSE_REWRITE_FALLBACK_WARNING = (
    "LLM clause rewriting failed for some clauses; template rewrites were used instead."
)


@runtime_checkable
class ContractAnalyzer(Protocol):
    """Analyzer interface used by the graph.

    The last three methods (facts, missing clauses, rewrites) are optional for
    duck-typed analyzers: the graph falls back to the rule-based analyzer when
    one is missing or raises.
    """

    async def summarize_contract(self, text: str, contract_type: str | None = None) -> str:
        ...

    async def segment_clauses(self, text: str) -> list[Clause]:
        ...

    async def classify_risks(
        self,
        clauses: list[Clause],
        contract_type: str | None = None,
        party: str | None = None,
    ) -> list[RiskFinding]:
        """Findings with `disadvantaged_party` set; `party` is the user's role id or None."""
        ...

    async def extract_contract_facts(
        self,
        clauses: list[Clause],
        contract_type: str | None,
    ) -> list[ExtractedFact]:
        """Facts for the statutory checks (see facts.py); never limits or verdicts."""
        ...

    async def detect_missing_clauses(
        self,
        clauses: list[Clause],
        contract_type: str | None,
    ) -> dict[str, TopicPresence]:
        """Presence of each checklist topic id for the contract type."""
        ...

    async def suggest_rewrites(
        self,
        items: list[tuple[Clause, list[RiskFinding]]],
        contract_type: str | None,
        party: str | None,
    ) -> list[ClauseRewrite]:
        """One rewrite per given clause, covering all of its findings."""
        ...

    async def build_legal_queries(
        self, findings: list[RiskFinding], contract_type: str | None = None
    ) -> dict[str, str]:
        """Return exactly one Yargı search query per finding, keyed by finding id.

        The graph passes `contract_type` only when it is known, so duck-typed
        analyzers without the parameter keep working (same for rewrite_query).
        """
        ...

    async def grade_decisions(
        self,
        finding: RiskFinding,
        decisions: list[YargiDecision],
    ) -> list[DecisionAssessment]:
        """Grade each decision for the finding; output is aligned with `decisions`."""
        ...

    async def rewrite_query(
        self,
        finding: RiskFinding,
        previous_queries: list[str],
        feedback: str,
        contract_type: str | None = None,
    ) -> str:
        """Return a new search query after `previous_queries` failed for `feedback` reasons."""
        ...

    def drain_warnings(self) -> list[str]:
        """Return and clear the warnings recorded since the last call."""
        ...


class WarningCollector:
    """Mixin implementing the `drain_warnings` side-channel."""

    def __init__(self) -> None:
        self._warnings: list[str] = []

    def _warn(self, message: str) -> None:
        if message not in self._warnings:
            self._warnings.append(message)

    def drain_warnings(self) -> list[str]:
        warnings, self._warnings = self._warnings, []
        return warnings


def drain_analyzer_warnings(analyzer: object) -> list[str]:
    """Drain warnings from an analyzer; tolerates test doubles without the method."""
    drain = getattr(analyzer, "drain_warnings", None)
    return list(drain()) if callable(drain) else []
