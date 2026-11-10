"""Deterministic statutory limit checks.

The analyzer (LLM or regex) extracts facts; the rules here compare them with
statutory limits. Each rule carries its verified legal basis from statutes.py.
A violation becomes a finding with confidence 1.0 and `detected_by =
"statutory_rule"`; an analyzer finding on the same clause and category is
merged into it instead of being counted twice.

Lease rules apply to residential and roofed-workplace leases (TBK m.339); when
the premises kind cannot be told from the text the result is needs_review.
"""

from collections.abc import Callable
from dataclasses import dataclass

from .contract_types import BOTH
from .models import ExtractedFact, LegalReference, RiskFinding, StatutoryCheck
from .statutes import provision

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

Facts = dict[str, ExtractedFact]


@dataclass(frozen=True)
class StatutoryRule:
    id: str
    contract_type: str
    title: str
    category: str
    severity: str
    basis_key: str
    recommendation: str
    evaluate: Callable[["StatutoryRule", Facts, float | None], StatutoryCheck]

    @property
    def basis(self) -> LegalReference:
        return provision(self.basis_key)

    def result(
        self,
        status: str,
        explanation: str,
        *,
        fact: ExtractedFact | None = None,
        value: str | None = None,
        limit: str | None = None,
    ) -> StatutoryCheck:
        return StatutoryCheck(
            rule_id=self.id,
            title=self.title,
            status=status,  # type: ignore[arg-type]
            clause_id=fact.clause_id if fact else None,
            extracted_value=value,
            limit=limit,
            explanation=explanation,
            legal_basis=self.basis,
            extracted_by=fact.extracted_by if fact else None,
        )


def _fmt(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _premises_known(facts: Facts) -> bool:
    return "premises_kind" in facts


_PREMISES_NOTE = (
    " Sözleşmeden kiralananın konut veya çatılı işyeri olduğu anlaşılamadığı için sonuç "
    "manuel kontrol gerektirir."
)


def _deposit(rule: StatutoryRule, facts: Facts, _: float | None) -> StatutoryCheck:
    months_fact = facts.get("deposit_months")
    months = float(months_fact.value) if months_fact else None
    fact = months_fact
    value_text = f"{_fmt(months)} aylık kira" if months is not None else None
    if months is None and "deposit_amount" in facts and "monthly_rent" in facts:
        rent = float(facts["monthly_rent"].value)
        if rent > 0:
            fact = facts["deposit_amount"]
            months = round(float(fact.value) / rent, 2)
            value_text = f"{_fmt(float(fact.value))} TL ({_fmt(months)} aylık kira)"
    limit = "En fazla 3 aylık kira bedeli"
    if months is None:
        return rule.result("not_applicable", "Sözleşmede güvence bedelinin tutarı veya kaç aylık kira olduğu tespit edilemedi.", limit=limit)
    if months <= 3:
        return rule.result("ok", "Güvence bedeli üç aylık kira bedeli sınırı içinde.", fact=fact, value=value_text, limit=limit)
    text = f"Güvence bedeli {value_text} olarak belirlenmiş; yasal üst sınır üç aylık kira bedelidir."
    if not _premises_known(facts):
        return rule.result("needs_review", text + _PREMISES_NOTE, fact=fact, value=value_text, limit=limit)
    return rule.result("violation", text + " Sınırı aşan kısım için kiracıdan güvence istenemez.", fact=fact, value=value_text, limit=limit)


def _rent_increase(rule: StatutoryRule, facts: Facts, cpi: float | None) -> StatutoryCheck:
    index_fact = facts.get("rent_increase_index")
    percent_fact = facts.get("rent_increase_percent")
    limit = "Bir önceki kira yılının TÜFE 12 aylık ortalama değişim oranı"
    if cpi is not None:
        limit += f" (ayarlanan değer: %{_fmt(cpi)})"
    if index_fact and index_fact.value == "tufe_12m_avg" and percent_fact is None:
        return rule.result("ok", "Kira artışı TÜFE'nin on iki aylık ortalama değişimine bağlanmış; yasal ölçüyle uyumlu.", fact=index_fact, value="TÜFE 12 aylık ortalama", limit=limit)
    if percent_fact is not None:
        percent = float(percent_fact.value)
        value = f"%{_fmt(percent)}"
        if cpi is None:
            return rule.result(
                "needs_review",
                f"Sözleşmede sabit %{_fmt(percent)} artış öngörülmüş. Güncel TÜFE 12 aylık ortalama değişim oranı "
                "ayarlanmadığı için sınırı aşıp aşmadığı otomatik kontrol edilemedi; yenileme dönemindeki oranla karşılaştırın.",
                fact=percent_fact, value=value, limit=limit,
            )
        if percent <= cpi:
            return rule.result("ok", f"Öngörülen %{_fmt(percent)} artış, ayarlanan TÜFE 12 aylık ortalama değişim oranının (%{_fmt(cpi)}) altında.", fact=percent_fact, value=value, limit=limit)
        text = f"Öngörülen %{_fmt(percent)} artış, TÜFE 12 aylık ortalama değişim oranını (%{_fmt(cpi)}) aşıyor; aşan kısım için anlaşma geçersizdir."
        if not _premises_known(facts):
            return rule.result("needs_review", text + _PREMISES_NOTE, fact=percent_fact, value=value, limit=limit)
        return rule.result("violation", text, fact=percent_fact, value=value, limit=limit)
    if index_fact is not None:
        names = {"tufe": "TÜFE (ortalama belirtilmemiş)", "ufe": "ÜFE", "other": "başka bir ölçüt"}
        value = names.get(str(index_fact.value), str(index_fact.value))
        return rule.result("needs_review", f"Kira artışı {value} esas alınarak belirlenmiş; yasal ölçü TÜFE'nin on iki aylık ortalama değişimidir, artışın bu oranı aşmadığını kontrol edin.", fact=index_fact, value=value, limit=limit)
    return rule.result("not_applicable", "Sözleşmede yenilenen dönem için kira artışı hükmü tespit edilemedi.", limit=limit)


def _penalty(rule: StatutoryRule, facts: Facts, _: float | None) -> StatutoryCheck:
    present = [facts[name] for name in ("late_payment_penalty", "acceleration_clause") if name in facts and facts[name].value is True]
    limit = "Geç ödemeye ceza koşulu veya muacceliyet kaydı konulamaz"
    if not present:
        return rule.result("not_applicable", "Kiranın geç ödenmesine bağlı ceza koşulu veya muacceliyet kaydı tespit edilemedi.", limit=limit)
    kinds = []
    if "late_payment_penalty" in facts and facts["late_payment_penalty"].value is True:
        kinds.append("ceza koşulu")
    if "acceleration_clause" in facts and facts["acceleration_clause"].value is True:
        kinds.append("sonraki kiraların muaccel olması")
    value = " ve ".join(kinds)
    text = f"Kiranın zamanında ödenmemesi hâlinde {value} öngörülmüş; konut ve çatılı işyeri kiralarında bu tür anlaşmalar geçersizdir."
    if not _premises_known(facts):
        return rule.result("needs_review", text + _PREMISES_NOTE, fact=present[0], value=value, limit=limit)
    return rule.result("violation", text, fact=present[0], value=value, limit=limit)


def _eviction(rule: StatutoryRule, facts: Facts, _: float | None) -> StatutoryCheck:
    fact = facts.get("eviction_undertaking")
    limit = "Tahliye taahhüdü kiralananın tesliminden sonra verilmelidir"
    if fact is None:
        return rule.result("not_applicable", "Sözleşmede tahliye taahhüdü tespit edilemedi.", limit=limit)
    if fact.value == "after_handover":
        return rule.result("ok", "Tahliye taahhüdünün teslimden sonra verileceği belirtilmiş.", fact=fact, value="teslimden sonra", limit=limit)
    if fact.value == "with_contract":
        return rule.result(
            "violation",
            "Tahliye taahhüdü sözleşmeyle birlikte, yani kiralanan teslim edilmeden alınmış görünüyor; "
            "teslimden önce verilen taahhüde dayanılarak tahliye istenemez.",
            fact=fact, value="sözleşmeyle birlikte", limit=limit,
        )
    return rule.result("needs_review", "Tahliye taahhüdü var ancak tarihinin teslimden sonra olup olmadığı anlaşılamıyor.", fact=fact, value="tarih belirsiz", limit=limit)


def _probation(rule: StatutoryRule, facts: Facts, _: float | None) -> StatutoryCheck:
    fact = facts.get("probation_months")
    limit = "En çok 2 ay (toplu iş sözleşmesiyle 4 ay)"
    if fact is None:
        return rule.result("not_applicable", "Sözleşmede deneme süresi tespit edilemedi.", limit=limit)
    months = float(fact.value)
    value = f"{_fmt(months)} ay"
    if months <= 2:
        return rule.result("ok", "Deneme süresi iki aylık yasal sınır içinde.", fact=fact, value=value, limit=limit)
    if months <= 4 and "collective_agreement" in facts:
        return rule.result("needs_review", "Deneme süresi iki ayı aşıyor; toplu iş sözleşmesiyle dört aya kadar uzatılabildiği için dayanağını kontrol edin.", fact=fact, value=value, limit=limit)
    return rule.result("violation", f"Deneme süresi {value} olarak belirlenmiş; yasal üst sınır iki aydır (toplu iş sözleşmesiyle dört ay).", fact=fact, value=value, limit=limit)


def _notice(rule: StatutoryRule, facts: Facts, _: float | None) -> StatutoryCheck:
    fact = facts.get("notice_weeks")
    limit = "Kıdeme göre en az 2 / 4 / 6 / 8 hafta"
    if fact is None:
        return rule.result("not_applicable", "Sözleşmede fesih bildirim süresi tespit edilemedi.", limit=limit)
    weeks = float(fact.value)
    value = f"{_fmt(weeks)} hafta"
    if weeks < 2:
        return rule.result("violation", f"Bildirim süresi {value}; kanundaki en kısa bildirim süresi (altı aydan az kıdem için) iki haftadır ve süreler asgaridir.", fact=fact, value=value, limit=limit)
    if weeks < 8:
        return rule.result("needs_review", f"Bildirim süresi {value}; kıdemi uzun işçiler için kanunda daha uzun asgari süreler (dört, altı, sekiz hafta) vardır, her kıdem için kontrol edin.", fact=fact, value=value, limit=limit)
    return rule.result("ok", "Bildirim süresi kanundaki en uzun asgari süreyi de karşılıyor.", fact=fact, value=value, limit=limit)


def _non_compete(rule: StatutoryRule, facts: Facts, _: float | None) -> StatutoryCheck:
    fact = facts.get("non_compete_years")
    limit = "Özel durumlar dışında en çok 2 yıl"
    if fact is None:
        return rule.result("not_applicable", "Sözleşmede süreli bir rekabet yasağı tespit edilemedi.", limit=limit)
    years = float(fact.value)
    value = f"{_fmt(years)} yıl"
    if years <= 2:
        return rule.result("ok", "Rekabet yasağının süresi iki yıllık sınır içinde; yer ve iş türü bakımından da makul olmalıdır.", fact=fact, value=value, limit=limit)
    return rule.result("violation", f"Rekabet yasağı {value} olarak belirlenmiş; süre özel durum ve koşullar dışında iki yılı aşamaz ve hâkim aşırı yasağı sınırlayabilir.", fact=fact, value=value, limit=limit)


RULES: tuple[StatutoryRule, ...] = (
    StatutoryRule("lease_deposit_cap", "lease", "Güvence bedeli üst sınırı", "deposit_forfeiture", "high", "tbk_342",
                  "Güvence bedelini en fazla üç aylık kira bedeli olarak belirleyin ve vadeli tasarruf hesabına yatırılmasını öngörün.", _deposit),
    StatutoryRule("lease_rent_increase_cap", "lease", "Yenileme döneminde kira artışı sınırı", "rent_increase", "high", "tbk_344",
                  "Artışı bir önceki kira yılının TÜFE 12 aylık ortalama değişim oranıyla sınırlayın.", _rent_increase),
    StatutoryRule("lease_penalty_acceleration", "lease", "Geç ödemede ceza koşulu ve muacceliyet yasağı", "penalty_clause", "high", "tbk_346",
                  "Geç ödeme için ceza koşulu ve muacceliyet kaydını çıkarın; yalnızca kanuni temerrüt sonuçlarına dayanın.", _penalty),
    StatutoryRule("lease_eviction_undertaking_date", "lease", "Tahliye taahhüdünün tarihi", "eviction_undertaking", "high", "tbk_352",
                  "Tahliye taahhüdünü sözleşmeden çıkarın; gerekiyorsa kiralananın tesliminden sonra ayrı bir belgeyle alın.", _eviction),
    StatutoryRule("employment_probation_cap", "employment", "Deneme süresi üst sınırı", "probation_period", "high", "ik_15",
                  "Deneme süresini en çok iki ay olarak belirleyin.", _probation),
    StatutoryRule("employment_notice_minimum", "employment", "Fesih bildirim süreleri", "termination", "medium", "ik_17",
                  "Bildirim sürelerini kıdeme göre en az iki, dört, altı ve sekiz hafta olacak şekilde düzenleyin.", _notice),
    StatutoryRule("employment_non_compete_cap", "employment", "Rekabet yasağı süresi", "non_compete", "high", "tbk_445",
                  "Rekabet yasağını en çok iki yılla, belirli bir bölge ve iş türüyle sınırlayın.", _non_compete),
)


def run_statutory_checks(
    facts: list[ExtractedFact],
    contract_type: str | None,
    cpi_12m_average_change: float | None,
) -> list[StatutoryCheck]:
    by_name = {fact.name: fact for fact in facts}
    return [
        rule.evaluate(rule, by_name, cpi_12m_average_change)
        for rule in RULES
        if rule.contract_type == contract_type
    ]


def merge_violations(
    findings: list[RiskFinding],
    checks: list[StatutoryCheck],
    clause_order: list[str] | None = None,
) -> tuple[list[RiskFinding], list[StatutoryCheck]]:
    """Turn violations into findings, merging same clause+category analyzer findings.

    Returns findings (in clause order when `clause_order` is given, renumbered)
    and the checks with `finding_id` filled in.
    """
    rules = {rule.id: rule for rule in RULES}
    merged = list(findings)
    check_to_index: dict[int, int] = {}
    for check_index, check in enumerate(checks):
        if check.status != "violation":
            continue
        rule = rules[check.rule_id]
        existing = next(
            (
                index
                for index, finding in enumerate(merged)
                if finding.category == rule.category
                and finding.detected_by != "statutory_rule"
                and (check.clause_id is None or finding.clause_id in (None, check.clause_id))
            ),
            None,
        )
        severity = rule.severity
        if existing is not None and _SEVERITY_RANK[merged[existing].severity] > _SEVERITY_RANK[severity]:
            severity = merged[existing].severity
        finding = RiskFinding(
            id="pending",
            category=rule.category,
            severity=severity,  # type: ignore[arg-type]
            explanation=check.explanation,
            recommendation=rule.recommendation,
            confidence=1.0,
            clause_id=check.clause_id or (merged[existing].clause_id if existing is not None else None),
            disadvantaged_party=BOTH,
            detected_by="statutory_rule",
            statutory_check_id=check.rule_id,
            legal_references=[check.legal_basis],
        )
        if existing is None:
            merged.append(finding)
            check_to_index[check_index] = len(merged) - 1
        else:
            merged[existing] = finding
            check_to_index[check_index] = existing
    positions = list(range(len(merged)))
    if clause_order:
        rank = {clause_id: index for index, clause_id in enumerate(clause_order)}
        positions.sort(key=lambda i: rank.get(merged[i].clause_id or "", len(rank)))
    new_id = {old: f"finding-{new}" for new, old in enumerate(positions, start=1)}
    renumbered = [merged[old].model_copy(update={"id": new_id[old]}) for old in positions]
    updated_checks = [
        check.model_copy(update={"finding_id": new_id[check_to_index[index]]})
        if index in check_to_index
        else check
        for index, check in enumerate(checks)
    ]
    return renumbered, updated_checks
