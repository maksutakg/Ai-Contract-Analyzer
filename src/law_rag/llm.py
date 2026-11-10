"""Gemini/Gemma-backed contract analyzer.

Kept import-compatible: `ContractAnalyzer`, `FakeContractAnalyzer`,
`canonicalize_risk_category`, `category_from_finding` and
`normalize_risk_findings` are still importable from here.
"""

from typing import Any

from google import genai

from . import prompts
from .call_gate import CallGate
from .analyzer_base import (
    CLASSIFY_FALLBACK_WARNING,
    GRADE_FALLBACK_WARNING,
    QUERY_FALLBACK_WARNING,
    REWRITE_FALLBACK_WARNING,
    SUMMARY_FALLBACK_WARNING,
    ContractAnalyzer,
    WarningCollector,
)
from .categories import (
    canonicalize_risk_category,
    category_from_finding,
    normalize_risk_findings,
)
from .config import Settings, settings
from .contract_types import default_disadvantaged, normalize_disadvantaged
from .crag import keyword_grade
from .fake_analyzer import FakeContractAnalyzer
from .llm_steps import GeminiExtraStepsMixin
from .models import Clause, DecisionAssessment, RiskFinding, YargiDecision
from .text_utils import json_array_from_text, searchable, split_text_by_budget

__all__ = [
    "ContractAnalyzer",
    "FakeContractAnalyzer",
    "GeminiContractAnalyzer",
    "canonicalize_risk_category",
    "category_from_finding",
    "merge_findings",
    "normalize_risk_findings",
]

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_GRADE_ALIASES = {
    "relevant": "relevant",
    "ilgili": "relevant",
    "ambiguous": "ambiguous",
    "belirsiz": "ambiguous",
    "partially relevant": "ambiguous",
    "irrelevant": "irrelevant",
    "ilgisiz": "irrelevant",
    "not relevant": "irrelevant",
}
_MAX_SUMMARY_COMBINE_ROUNDS = 4


# Kept under its old name for existing imports.
_CallGate = CallGate


def merge_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
    """Normalise categories, drop duplicates and renumber ids.

    Duplicates are findings with the same (category, clause). Rule-based
    findings (from per-batch fallback) are additionally limited to one per
    category across the whole contract, as the rule-based analyzer itself
    would produce on the full text. For duplicates the more severe (then more
    confident) finding wins, keeping the position of the first occurrence.
    """
    merged: dict[tuple[str, str | None], RiskFinding] = {}
    for finding in normalize_risk_findings(findings):
        key = (finding.category, finding.clause_id)
        if finding.detected_by == "rule_based":
            key = (finding.category, "rule_based")
        current = merged.get(key)
        if current is None:
            merged[key] = finding
            continue
        if (_SEVERITY_RANK[finding.severity], finding.confidence) > (
            _SEVERITY_RANK[current.severity],
            current.confidence,
        ):
            merged[key] = finding
    return [
        finding.model_copy(update={"id": f"finding-{index}"})
        for index, finding in enumerate(merged.values(), start=1)
    ]


def _clean_query(text: str) -> str:
    line = next((line for line in text.strip().splitlines() if line.strip()), "")
    line = line.strip().strip("`").strip()
    for prefix in ("Sorgu:", "Query:", "Arama sorgusu:"):
        if line.casefold().startswith(prefix.casefold()):
            line = line[len(prefix) :].strip()
    if line.startswith('"') and line.endswith('"') and line.count('"') == 2:
        line = line[1:-1]
    return line.strip()


class GeminiContractAnalyzer(GeminiExtraStepsMixin, WarningCollector):
    def __init__(self, app_settings: Settings = settings, gate: CallGate | None = None) -> None:
        super().__init__()
        if not app_settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiContractAnalyzer.")
        self._settings = app_settings
        self._client = genai.Client(api_key=app_settings.gemini_api_key)
        self._fallback = FakeContractAnalyzer()
        # A shared gate paces this analyzer together with OCR of the same request.
        self._gate = gate or _CallGate(
            self._setting("llm_max_concurrency"),
            self._setting("llm_min_interval_seconds"),
        )

    def _setting(self, name: str) -> Any:
        """Read a setting, defaulting for duck-typed settings objects that lack it."""
        return getattr(self._settings, name, Settings.model_fields[name].default)

    async def _generate(self, prompt: str) -> str:
        async def call() -> Any:
            return await self._client.aio.models.generate_content(
                model=self._settings.gemini_model,
                contents=prompt,
            )

        response = await self._gate.run(call)
        return (response.text or "").strip()

    # ------------------------------------------------------------------ summary
    async def summarize_contract(self, text: str, contract_type: str | None = None) -> str:
        budget = self._setting("llm_summary_chunk_chars")
        try:
            if len(text) <= budget:
                summary = await self._generate(prompts.summary_prompt(text, contract_type))
                return summary or "Özet üretilemedi."
            parts = split_text_by_budget(text, budget)
            partials = [
                await self._generate(
                    prompts.summary_part_prompt(part, contract_type, index, len(parts))
                )
                for index, part in enumerate(parts, start=1)
            ]
            for _ in range(_MAX_SUMMARY_COMBINE_ROUNDS):
                partials = [partial for partial in partials if partial]
                combine_prompt = prompts.summary_combine_prompt(partials, contract_type)
                if len(combine_prompt) <= budget * 2 or len(partials) <= 1:
                    break
                groups = split_text_by_budget("\n\n".join(partials), budget)
                partials = [
                    await self._generate(
                        prompts.summary_part_prompt(group, contract_type, index, len(groups))
                    )
                    for index, group in enumerate(groups, start=1)
                ]
            summary = await self._generate(prompts.summary_combine_prompt(partials, contract_type))
            return summary or "Özet üretilemedi."
        except Exception:
            self._warn(SUMMARY_FALLBACK_WARNING)
            return await self._fallback.summarize_contract(text, contract_type)

    async def segment_clauses(self, text: str) -> list[Clause]:
        return await self._fallback.segment_clauses(text)

    # ----------------------------------------------------------- classification
    def _clause_batches(self, clauses: list[Clause]) -> list[tuple[list[Clause], str]]:
        budget = self._setting("llm_clause_batch_chars")
        batches: list[tuple[list[Clause], str]] = []
        current_clauses: list[Clause] = []
        current_lines: list[str] = []
        current_len = 0

        def flush() -> None:
            nonlocal current_clauses, current_lines, current_len
            if current_lines:
                batches.append((current_clauses, "\n".join(current_lines)))
            current_clauses, current_lines, current_len = [], [], 0

        for clause in clauses:
            for line in prompts.clause_lines(clause, budget):
                if current_lines and current_len + len(line) + 1 > budget:
                    flush()
                if clause not in current_clauses:
                    current_clauses.append(clause)
                current_lines.append(line)
                current_len += len(line) + 1
        flush()
        return batches

    def _parse_findings(
        self,
        raw: str,
        valid_clause_ids: set[str],
        contract_type: str | None = None,
    ) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        for item in json_array_from_text(raw or "[]"):
            clause_id = item.get("clause_id")
            if clause_id not in valid_clause_ids:
                clause_id = None
            severity = str(item.get("severity", "medium")).strip().lower()
            try:
                confidence = min(1.0, max(0.0, float(item.get("confidence", 0.7))))
            except (TypeError, ValueError):
                confidence = 0.7
            category = canonicalize_risk_category(str(item.get("category", "general_risk")))
            disadvantaged = normalize_disadvantaged(contract_type, item.get("disadvantaged_party"))
            if disadvantaged is None:
                # Unknown or missing: use the static mapping rather than guessing.
                disadvantaged = default_disadvantaged(contract_type, category)
            findings.append(
                RiskFinding(
                    id=f"finding-{len(findings) + 1}",
                    category=category,
                    severity=severity if severity in _SEVERITY_RANK else "medium",  # type: ignore[arg-type]
                    explanation=str(item.get("explanation", "Risk hukuki inceleme gerektiriyor.")),
                    recommendation=str(item.get("recommendation", "Maddeyi gözden geçirip revize edin.")),
                    confidence=confidence,
                    clause_id=clause_id,
                    disadvantaged_party=disadvantaged,
                    detected_by="llm",
                )
            )
        return findings

    async def classify_risks(
        self,
        clauses: list[Clause],
        contract_type: str | None = None,
        party: str | None = None,
    ) -> list[RiskFinding]:
        max_findings = self._setting("llm_max_findings_per_batch")
        batches = self._clause_batches(clauses)
        collected: list[RiskFinding] = []
        for number, (batch_clauses, payload) in enumerate(batches, start=1):
            prompt = prompts.classify_prompt(
                payload, contract_type, max_findings, number, len(batches), party=party
            )
            try:
                raw = await self._generate(prompt)
                batch_findings = self._parse_findings(
                    raw, {clause.id for clause in batch_clauses}, contract_type
                )
                collected.extend(batch_findings[:max_findings])
            except Exception:
                self._warn(CLASSIFY_FALLBACK_WARNING)
                collected.extend(
                    await self._fallback.classify_risks(batch_clauses, contract_type, party)
                )
        return merge_findings(collected)

    # ---------------------------------------------------------------- retrieval
    async def build_legal_queries(
        self, findings: list[RiskFinding], contract_type: str | None = None
    ) -> dict[str, str]:
        queries: dict[str, str] = {}
        for finding in findings:
            try:
                query = _clean_query(await self._generate(prompts.legal_query_prompt(finding)))
            except Exception:
                query = ""
            if not query:
                self._warn(QUERY_FALLBACK_WARNING)
                query = (await self._fallback.build_legal_queries([finding], contract_type))[finding.id]
            queries[finding.id] = query
        return queries

    async def grade_decisions(
        self,
        finding: RiskFinding,
        decisions: list[YargiDecision],
    ) -> list[DecisionAssessment]:
        if not decisions:
            return []
        category = category_from_finding(finding)
        by_index: dict[int, DecisionAssessment] = {}
        try:
            raw = await self._generate(prompts.grade_prompt(finding, decisions))
            for item in json_array_from_text(raw):
                try:
                    index = int(item.get("index"))
                except (TypeError, ValueError):
                    continue
                label = _GRADE_ALIASES.get(searchable(str(item.get("label", ""))).strip())
                if label is None or not 1 <= index <= len(decisions):
                    continue
                reason = str(item.get("reason") or "").strip() or "Gerekçe belirtilmedi."
                by_index[index] = DecisionAssessment(grade=label, reason=reason, graded_by="llm")  # type: ignore[arg-type]
        except Exception:
            by_index = {}
        assessments: list[DecisionAssessment] = []
        for index, decision in enumerate(decisions, start=1):
            assessment = by_index.get(index)
            if assessment is None:
                self._warn(GRADE_FALLBACK_WARNING)
                assessment = keyword_grade(decision, category)
            assessments.append(assessment)
        return assessments

    async def rewrite_query(
        self,
        finding: RiskFinding,
        previous_queries: list[str],
        feedback: str,
        contract_type: str | None = None,
    ) -> str:
        try:
            query = _clean_query(
                await self._generate(prompts.rewrite_query_prompt(finding, previous_queries, feedback))
            )
        except Exception:
            query = ""
        if not query:
            self._warn(REWRITE_FALLBACK_WARNING)
            return await self._fallback.rewrite_query(finding, previous_queries, feedback, contract_type)
        tried = {searchable(" ".join(previous.split())) for previous in previous_queries}
        if searchable(" ".join(query.split())) in tried:
            # The model repeated itself; use the deterministic broadening ladder instead.
            return await self._fallback.rewrite_query(finding, previous_queries, feedback, contract_type)
        return query
