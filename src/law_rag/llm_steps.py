"""Gemini steps added for statutory facts, missing clauses and clause rewrites.

Mixed into GeminiContractAnalyzer, which provides `_generate`, `_warn`,
`_setting`, `_clause_batches` and `_fallback` (the rule-based analyzer). Every
step parses model output tolerantly (no JSON mode on Gemma), falls back to the
rule-based behaviour per batch or per item, and records a warning that ends up
in the report's limitations.
"""

import re
from typing import Any

from . import prompts
from .analyzer_base import (
    CLAUSE_REWRITE_FALLBACK_WARNING,
    FACTS_FALLBACK_WARNING,
    MISSING_CLAUSES_FALLBACK_WARNING,
)
from .facts import FACTS_BY_TYPE, coerce_fact_value, merge_facts
from .missing_clauses import checklist_for
from .models import Clause, ClauseRewrite, ExtractedFact, RiskFinding, TopicPresence
from .rewrites import template_rewrite
from .text_utils import json_array_from_text, searchable

# A rewrite that cites a statute is rejected: citations come only from statutes.py.
_CITATION_RE = re.compile(
    r"\b\d{4}\s*say[ıi]l[ıi]|\b(?:TBK|TTK|HMK|KVKK|FSEK)\b\s*(?:m\.|md\.|madde)\s*\d+"
    r"|kanunu?['’]?(?:n[ıu]n)?\s+\d+\s*['’.]?\s*(?:[a-zçğıöşü]*\s+)?madde",
    re.IGNORECASE,
)
_MAX_CLAUSE_CHARS_FOR_CHECKLIST = 400


def cites_statute(text: str) -> bool:
    return bool(_CITATION_RE.search(text or ""))


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    key = searchable(str(value)).strip()
    if key in {"true", "yes", "evet", "var", "present", "1"}:
        return True
    if key in {"false", "no", "hayir", "yok", "absent", "missing", "0"}:
        return False
    return None


class GeminiExtraStepsMixin:
    _fallback: Any

    # ---------------------------------------------------------- statutory facts
    async def extract_contract_facts(
        self,
        clauses: list[Clause],
        contract_type: str | None,
    ) -> list[ExtractedFact]:
        wanted = set(FACTS_BY_TYPE.get(contract_type or "", ()))
        if not wanted or not clauses:
            return []
        llm_facts: list[ExtractedFact] = []
        regex_facts: list[ExtractedFact] = []
        for batch_clauses, payload in self._clause_batches(clauses):
            try:
                raw = await self._generate(prompts.facts_prompt(payload, contract_type))
                valid_ids = {clause.id for clause in batch_clauses}
                for item in json_array_from_text(raw or "[]"):
                    name = str(item.get("fact") or item.get("name") or "").strip()
                    if name not in wanted:
                        continue
                    value = coerce_fact_value(name, item.get("value"))
                    if value is None:
                        continue
                    clause_id = item.get("clause_id")
                    llm_facts.append(
                        ExtractedFact(
                            name=name,
                            value=value,
                            clause_id=clause_id if clause_id in valid_ids else None,
                            extracted_by="llm",
                        )
                    )
            except Exception:
                self._warn(FACTS_FALLBACK_WARNING)
                regex_facts.extend(
                    await self._fallback.extract_contract_facts(batch_clauses, contract_type)
                )
        # The first value per fact wins; regex fills facts the model did not report.
        unique: dict[str, ExtractedFact] = {}
        for fact in llm_facts + regex_facts:
            unique.setdefault(fact.name, fact)
        gap_fill = await self._fallback.extract_contract_facts(clauses, contract_type)
        return merge_facts(list(unique.values()), gap_fill)

    # ---------------------------------------------------------- missing clauses
    async def detect_missing_clauses(
        self,
        clauses: list[Clause],
        contract_type: str | None,
    ) -> dict[str, TopicPresence]:
        topics = checklist_for(contract_type)
        fallback = await self._fallback.detect_missing_clauses(clauses, contract_type)
        budget = self._setting("llm_clause_batch_chars")
        per_clause = max(120, min(_MAX_CLAUSE_CHARS_FOR_CHECKLIST, budget // max(1, len(clauses))))
        lines = []
        for clause in clauses:
            title = f" | {clause.title}" if clause.title else ""
            lines.append(f"{clause.id}{title}: {clause.text[:per_clause]}")
        payload = "\n".join(lines)[: budget * 2]
        verdicts: dict[str, TopicPresence] = {}
        try:
            raw = await self._generate(prompts.missing_clauses_prompt(payload, topics))
            known = {topic.id for topic in topics}
            for item in json_array_from_text(raw or "[]"):
                topic = str(item.get("topic") or "").strip()
                present = _as_bool(item.get("present"))
                if topic in known and present is not None:
                    verdicts[topic] = TopicPresence(present=present, detected_by="llm")
        except Exception:
            verdicts = {}
        if len(verdicts) < len(topics):
            self._warn(MISSING_CLAUSES_FALLBACK_WARNING)
        return {topic.id: verdicts.get(topic.id) or fallback[topic.id] for topic in topics}

    # ------------------------------------------------------------ clause rewrite
    def _rewrite_batches(
        self, items: list[tuple[Clause, list[RiskFinding]]]
    ) -> list[list[tuple[Clause, list[RiskFinding]]]]:
        budget = self._setting("llm_clause_batch_chars")
        batches: list[list[tuple[Clause, list[RiskFinding]]]] = []
        current: list[tuple[Clause, list[RiskFinding]]] = []
        size = 0
        for clause, findings in items:
            item_size = len(clause.text) + sum(len(finding.explanation) + 40 for finding in findings)
            if current and size + item_size > budget:
                batches.append(current)
                current, size = [], 0
            current.append((clause, findings))
            size += item_size
        if current:
            batches.append(current)
        return batches

    async def suggest_rewrites(
        self,
        items: list[tuple[Clause, list[RiskFinding]]],
        contract_type: str | None,
        party: str | None,
    ) -> list[ClauseRewrite]:
        rewrites: dict[str, ClauseRewrite] = {}
        for batch in self._rewrite_batches(items):
            by_id = {clause.id: (clause, findings) for clause, findings in batch}
            try:
                raw = await self._generate(prompts.rewrite_clauses_prompt(batch, contract_type, party))
                parsed = json_array_from_text(raw or "[]")
            except Exception:
                parsed = []
            for item in parsed:
                clause_id = item.get("clause_id")
                suggested = str(item.get("suggested_text") or "").strip()
                rationale = str(item.get("rationale") or "").strip()
                if clause_id not in by_id or clause_id in rewrites or not suggested:
                    continue
                if cites_statute(suggested) or cites_statute(rationale):
                    continue
                clause, findings = by_id[clause_id]
                rewrites[clause_id] = ClauseRewrite(
                    clause_id=clause.id,
                    finding_ids=[finding.id for finding in findings],
                    original_text=clause.text,
                    suggested_text=suggested,
                    rationale=rationale or "Madde, tespit edilen riskleri giderecek şekilde yeniden yazıldı.",
                    generated_by="llm",
                )
        result: list[ClauseRewrite] = []
        for clause, findings in items:
            rewrite = rewrites.get(clause.id)
            if rewrite is None:
                self._warn(CLAUSE_REWRITE_FALLBACK_WARNING)
                rewrite = template_rewrite(clause, findings, contract_type)
            result.append(rewrite)
        return result
