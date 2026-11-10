"""Deterministic, rule-based contract analyzer.

Used offline (tests, `create_app(use_fake_clients=True)`, no API key), as the
fallback when Gemini calls fail, and as the baseline for evaluation. Every
method is deterministic so the whole pipeline can be tested without a network.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from .analyzer_base import WarningCollector
from .categories import category_from_finding, fallback_query, relevance_terms
from .contract_types import default_disadvantaged
from .crag import keyword_grade
from .facts import extract_facts_rule_based
from .missing_clauses import keyword_presence
from .models import (
    Clause,
    ClauseRewrite,
    DecisionAssessment,
    ExtractedFact,
    RiskFinding,
    TopicPresence,
    YargiDecision,
)
from .rewrites import template_rewrite
from .segmentation import PREAMBLE_ID, segment_clauses as rule_based_segment_clauses
from .text_utils import searchable


def _unquoted(query: str) -> str:
    return " ".join(query.replace('"', " ").split())


def _has(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


@dataclass(frozen=True)
class _Rule:
    """A keyword rule. `anchor` must match the clause's own text; `support` may
    use the neighbouring clauses (context) and the whole contract."""

    category: str
    anchor: Callable[[str], bool]
    support: Callable[[str, str, str | None], bool]  # (context, whole, contract_type)
    severity: str
    explanation: str
    recommendation: str
    confidence: float
    # Builds the explanation from the clause's original text when it should
    # quote what the clause actually says (default: the fixed explanation).
    explain: Callable[[str], str] | None = None


_COURT_RE = re.compile(r"([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü]+)\s+(?:mahkemeleri|MAHKEMELERİ|MAHKEMELERI|Mahkemeleri)")
_COURT_TOKEN_RE = re.compile(r"\b([a-z]{3,})\s+mahkemeleri\b")
_GENERIC_COURT_WORDS = frozenset(
    {
        "yetkili",
        "bulundugu",
        "yer",
        "ilgili",
        "gorevli",
        "genel",
        "ticaret",
        "hukuk",
        "sulh",
        "asliye",
        "ceza",
        "icra",
        "turk",
        "turkiye",
        "cumhuriyeti",
    }
)


def _has_named_court(own: str) -> bool:
    return any(match.group(1) not in _GENERIC_COURT_WORDS for match in _COURT_TOKEN_RE.finditer(own))


def _capitalize_tr(word: str, turkish: bool) -> str:
    if not word:
        return word
    if turkish:
        first = {"i": "İ", "ı": "I"}.get(word[0], word[0].upper())
        rest = word[1:].replace("I", "ı").replace("İ", "i").lower()
        return first + rest
    return word[:1].upper() + word[1:].lower()


def _jurisdiction_explanation(clause_text: str) -> str:
    """States only what the clause shows: the chosen courts, not where the property is."""
    turkish = any(char in clause_text for char in "çğıöşüÇĞİÖŞÜ")
    courts: list[str] = []
    for match in _COURT_RE.finditer(clause_text):
        court = match.group(1)
        if searchable(court) in _GENERIC_COURT_WORDS:
            continue
        if court.isupper():
            court = _capitalize_tr(court, turkish)
        if court not in courts:
            courts.append(court)
    if not courts:
        for match in _COURT_TOKEN_RE.finditer(searchable(clause_text)):
            token = match.group(1)
            if token in _GENERIC_COURT_WORDS:
                continue
            label = _capitalize_tr(token, False)
            if label not in courts:
                courts.append(label)
    named = " ve ".join(courts) or "seçilen"
    return (
        f"Yetki maddesi {named} mahkemelerini yetkili kılıyor. Taşınmazın bulunduğu yer veya "
        "davalının yerleşim yeri başka bir yerdeyse, bu seçim kesin yetki kuralları nedeniyle "
        "yetki itirazı riski doğurabilir."
    )


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "cash_payment",
        lambda own: "elden" in own,
        lambda ctx, whole, ct: _has(ctx, "odeme", "kira bedeli", "odenir"),
        "medium",
        "Kira bedelinin elden ödenmesi ispat ve mevzuata uyum riski doğurabilir.",
        "Kira ödemelerini banka kanalıyla ve açıklama bilgisiyle yapılacak şekilde düzenleyin.",
        0.86,
    ),
    _Rule(
        "deposit_forfeiture",
        lambda own: _has(own, "depozito", "guvence bedeli") and "iade edilmez" in own,
        lambda ctx, whole, ct: True,
        "high",
        "Depozitonun belirli hâllerde otomatik olarak iade edilmemesi orantısız yaptırım riski taşır.",
        "Depozito kesintisini gerçek zarar, belge ve mahsup prosedürüne bağlayın.",
        0.9,
    ),
    _Rule(
        "termination",
        lambda own: _has(own, "fesih", "feshedilir", "feshedebilir", "feshet", "terminate")
        and _has(own, "derhal", "tek tarafli", "unilateral"),
        lambda ctx, whole, ct: True,
        "high",
        "Derhal veya tek taraflı fesih hükmü manuel inceleme gerektirir.",
        "Fesih sebeplerini, bildirim süresini ve telafi hakkını netleştirin.",
        0.9,
    ),
    _Rule(
        "termination",
        lambda own: _has(own, "fesih", "feshedilir", "feshedebilir", "feshet", "terminate"),
        lambda ctx, whole, ct: True,
        "medium",
        "Fesih hükmü taraf dengesi ve bildirim koşulları açısından incelenmelidir.",
        "Fesih prosedürünü, süreleri ve sonuçları açık hâle getirin.",
        0.72,
    ),
    _Rule(
        "penalty_clause",
        lambda own: _has(own, "cezai sart", "penalty"),
        lambda ctx, whole, ct: True,
        "medium",
        "Cezai şart hükmü orantılılık açısından incelenmelidir.",
        "Cezai şart tutarını, üst sınırını ve uygulanma koşullarını kontrol edin.",
        0.85,
    ),
    _Rule(
        "unlawful_entry",
        lambda own: _has(own, "izni olmaksizin", "izin olmaksizin", "izni alinmaksizin"),
        lambda ctx, whole, ct: _has(ctx, "tasinmaz", "daire", "konut", "kiralanan"),
        "critical",
        "Kiracının izni olmadan konuta giriş hakkı konut dokunulmazlığı ve özel hayat riski doğurur.",
        "Giriş hakkını önceden bildirim, makul saat ve kiracı onayı şartlarına bağlayın.",
        0.95,
    ),
    _Rule(
        "eviction_undertaking",
        lambda own: _has(own, "tahliye taahhud", "tahliye taahhut"),
        lambda ctx, whole, ct: True,
        "high",
        "Tahliye taahhüdünün sözleşme ile birlikte alınması geçerlilik tartışması yaratabilir.",
        "Tahliye taahhüdünü sözleşme tarihinden sonra, serbest iradeyi gösterecek şekilde ayrı değerlendirin.",
        0.88,
    ),
    _Rule(
        "rent_increase",
        lambda own: _has(own, "%100", "100 oraninda", "yuzde 100"),
        lambda ctx, whole, ct: _has(ctx, "artir", "artis", "kira bedeli"),
        "high",
        "Yıllık %100 kira artışı yasal artış sınırlarıyla uyumsuz olabilir.",
        "Artış oranını uygulanabilir yasal sınır ve endekslerle uyumlu hâle getirin.",
        0.92,
    ),
    _Rule(
        "jurisdiction",
        _has_named_court,
        lambda ctx, whole, ct: True,
        "medium",
        "Yetki maddesi Ankara mahkemelerini yetkili kılıyor; taşınmazın bulunduğu yer başka bir yerdeyse yetki itirazı riski doğabilir.",
        "Yetki maddesini taşınmazın bulunduğu yer ve zorunlu yetki kuralları açısından kontrol edin.",
        0.76,
        _jurisdiction_explanation,
    ),
)


class FakeContractAnalyzer(WarningCollector):
    async def summarize_contract(self, text: str, contract_type: str | None = None) -> str:
        prefix = f"{contract_type} sözleşmesi" if contract_type else "Sözleşme"
        excerpt = text[:240].strip()
        return f"{prefix} için kural tabanlı özet: {excerpt}"

    async def segment_clauses(self, text: str) -> list[Clause]:
        return rule_based_segment_clauses(text)

    async def classify_risks(
        self,
        clauses: list[Clause],
        contract_type: str | None = None,
        party: str | None = None,
    ) -> list[RiskFinding]:
        """Keyword rules; at most one finding per category.

        A finding is attributed to the first clause whose own text matches the
        rule's anchor; neighbouring clauses only provide supporting context.
        `party` does not change detection: the side a finding works against
        comes from a static per-category mapping.
        """
        own_texts = [searchable(clause.text) for clause in clauses]
        whole = " ".join(own_texts)
        findings: list[RiskFinding] = []
        seen: set[str] = set()
        for rule in _RULES:
            if rule.category in seen:
                continue
            for index, clause in enumerate(clauses):
                if clause.id == PREAMBLE_ID:
                    continue
                own = own_texts[index]
                context = " ".join(own_texts[max(0, index - 1) : index + 2])
                if rule.anchor(own) and rule.support(context, whole, contract_type):
                    seen.add(rule.category)
                    findings.append(
                        RiskFinding(
                            id="pending",
                            category=rule.category,
                            severity=rule.severity,  # type: ignore[arg-type]
                            explanation=rule.explain(clause.text) if rule.explain else rule.explanation,
                            recommendation=rule.recommendation,
                            confidence=rule.confidence,
                            clause_id=clause.id,
                            disadvantaged_party=default_disadvantaged(contract_type, rule.category),
                            detected_by="rule_based",
                        )
                    )
                    break
        order = {clause.id: index for index, clause in enumerate(clauses)}
        findings.sort(key=lambda finding: order.get(finding.clause_id or "", len(order)))
        return [
            finding.model_copy(update={"id": f"finding-{index}"})
            for index, finding in enumerate(findings, start=1)
        ]

    async def extract_contract_facts(
        self,
        clauses: list[Clause],
        contract_type: str | None,
    ) -> list[ExtractedFact]:
        return extract_facts_rule_based(clauses, contract_type)

    async def detect_missing_clauses(
        self,
        clauses: list[Clause],
        contract_type: str | None,
    ) -> dict[str, TopicPresence]:
        return keyword_presence(clauses, contract_type)

    async def suggest_rewrites(
        self,
        items: list[tuple[Clause, list[RiskFinding]]],
        contract_type: str | None,
        party: str | None,
    ) -> list[ClauseRewrite]:
        return [template_rewrite(clause, findings, contract_type) for clause, findings in items]

    async def build_legal_queries(
        self, findings: list[RiskFinding], contract_type: str | None = None
    ) -> dict[str, str]:
        return {
            finding.id: fallback_query(category_from_finding(finding), contract_type)
            for finding in findings
        }

    async def grade_decisions(
        self,
        finding: RiskFinding,
        decisions: list[YargiDecision],
    ) -> list[DecisionAssessment]:
        category = category_from_finding(finding)
        return [keyword_grade(decision, category) for decision in decisions]

    async def rewrite_query(
        self,
        finding: RiskFinding,
        previous_queries: list[str],
        feedback: str,
        contract_type: str | None = None,
    ) -> str:
        """Deterministic broadening ladder; returns the first candidate not tried yet.

        1. the last query without quotes, 2. the first two relevance terms of the
        category, 3. the category's fallback query without quotes. If every
        candidate was already tried, the last query is returned unchanged and the
        graph treats the finding as exhausted.
        """
        category = category_from_finding(finding)
        last = previous_queries[-1] if previous_queries else fallback_query(category, contract_type)
        terms = relevance_terms(category)
        candidates = [
            _unquoted(last),
            " ".join(terms[:2]),
            _unquoted(fallback_query(category, contract_type)),
        ]
        tried = {_normalize_query(query) for query in previous_queries}
        for candidate in candidates:
            if candidate and _normalize_query(candidate) not in tried:
                return candidate
        return last


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", searchable(query)).strip()
