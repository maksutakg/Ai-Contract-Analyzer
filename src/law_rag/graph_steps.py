"""Graph node logic for party perspective, statutory checks, missing clauses and rewrites.

graph.py only wires these into the LangGraph pipeline. Analyzer steps that a
duck-typed analyzer does not implement run on the rule-based analyzer; a step
that raises falls back to it as well and records a limitation.
"""

from collections.abc import Callable
from typing import Any

from .analyzer_base import (
    CLAUSE_REWRITE_FALLBACK_WARNING,
    FACTS_FALLBACK_WARNING,
    MISSING_CLAUSES_FALLBACK_WARNING,
)
from .contract_types import CONTRACT_TYPES, apply_party, default_disadvantaged, guess_contract_type
from .fake_analyzer import FakeContractAnalyzer
from .missing_clauses import build_missing_clauses
from .models import ContractAnalysisState, RiskFinding, TopicPresence
from .rewrites import clauses_to_rewrite
from .statutes import ground_findings
from .statutory_rules import merge_violations, run_statutory_checks

GUESSED_TYPE_LIMITATION = (
    "No contract type was given; statutory checks and the missing-clause checklist used the "
    "keyword guess '{guess}'."
)
NO_TYPE_LIMITATION = (
    "No contract type was given or recognised; no statutory limit checks were run and a generic "
    "missing-clause checklist was used."
)
CPI_UNSET_LIMITATION = (
    "TUFE_12M_AVERAGE_CHANGE_PERCENT is not set; fixed rent increases are reported as needs_review."
)


def _setting(app_settings: Any, name: str, default: Any) -> Any:
    return getattr(app_settings, name, default)


def effective_contract_type(state: ContractAnalysisState) -> tuple[str | None, list[str]]:
    """Type for checks/checklists: the given type, else a keyword guess."""
    if state.contract_type in CONTRACT_TYPES:
        return state.contract_type, []
    if state.contract_type is None:
        guess = guess_contract_type(state.raw_text)
        if guess:
            return guess, [GUESSED_TYPE_LIMITATION.format(guess=guess)]
    return None, [NO_TYPE_LIMITATION]


def applicable(findings: list[RiskFinding]) -> list[RiskFinding]:
    return [finding for finding in findings if finding.applies_to_user]


class ExtraSteps:
    """Async node bodies; each returns (partial state update, limitations)."""

    def __init__(self, analyzer: object, app_settings: Any, warnings: Callable[[], list[str]]) -> None:
        self._analyzer = analyzer
        self._settings = app_settings
        self._warnings = warnings
        self._rule_based = FakeContractAnalyzer()

    async def _call(self, name: str, warning: str, *args: Any) -> tuple[Any, list[str]]:
        method = getattr(self._analyzer, name, None)
        if method is not None:
            try:
                return await method(*args), self._warnings()
            except Exception:
                return await getattr(self._rule_based, name)(*args), self._warnings() + [warning]
        return await getattr(self._rule_based, name)(*args), []

    async def check_statutes(self, state: ContractAnalysisState) -> tuple[dict, list[str]]:
        contract_type, limitations = effective_contract_type(state)
        findings = [
            finding
            if finding.disadvantaged_party is not None
            else finding.model_copy(
                update={"disadvantaged_party": default_disadvantaged(contract_type, finding.category)}
            )
            for finding in state.findings
        ]
        checks = []
        if _setting(self._settings, "statutory_checks_enabled", True) and contract_type:
            facts, warned = await self._call(
                "extract_contract_facts", FACTS_FALLBACK_WARNING, state.clauses, contract_type
            )
            limitations += warned
            cpi = _setting(self._settings, "tufe_12m_average_change_percent", None)
            checks = run_statutory_checks(list(facts), contract_type, cpi)
            if cpi is None and any(check.rule_id == "lease_rent_increase_cap" and check.status == "needs_review" for check in checks):
                limitations.append(CPI_UNSET_LIMITATION)
            findings, checks = merge_violations(
                findings, checks, [clause.id for clause in state.clauses]
            )
        findings = apply_party(ground_findings(findings, contract_type), state.party)
        return {"findings": findings, "statutory_checks": checks}, limitations

    async def detect_missing_clauses(self, state: ContractAnalysisState) -> tuple[dict, list[str]]:
        if not _setting(self._settings, "missing_clauses_enabled", True) or not state.clauses:
            return {"missing_clauses": []}, []
        contract_type, limitations = effective_contract_type(state)
        presence, warned = await self._call(
            "detect_missing_clauses", MISSING_CLAUSES_FALLBACK_WARNING, state.clauses, contract_type
        )
        verdicts = {
            topic: value if isinstance(value, TopicPresence) else TopicPresence(present=bool(value))
            for topic, value in dict(presence).items()
        }
        missing = build_missing_clauses(verdicts, contract_type, state.party)
        return {"missing_clauses": missing}, limitations + warned

    async def suggest_rewrites(self, state: ContractAnalysisState) -> tuple[dict, list[str]]:
        items = clauses_to_rewrite(state.clauses, state.findings)
        if not _setting(self._settings, "clause_rewrites_enabled", True) or not items:
            return {"rewrites": []}, []
        contract_type, _ = effective_contract_type(state)
        rewrites, warned = await self._call(
            "suggest_rewrites", CLAUSE_REWRITE_FALLBACK_WARNING, items, contract_type, state.party
        )
        return {"rewrites": list(rewrites)}, warned
