"""Fact extraction for the statutory limit checks.

The extractor's only job is to pull facts out of clause text; statutory_rules.py
compares them with the limits. The rule-based extractor below is regex based
and is used offline and as the fallback (and gap filler) for the LLM extractor.

Fact names and value types:
  premises_kind          "residential" | "workplace"
  monthly_rent           float, TL
  deposit_amount         float, TL
  deposit_months         float, months of rent
  rent_increase_percent  float, a fixed yearly increase
  rent_increase_index    "tufe_12m_avg" | "tufe" | "ufe" | "other"
  eviction_undertaking   "with_contract" | "after_handover" | "unknown"
  late_payment_penalty   bool, a penalty for late rent (lease)
  acceleration_clause    bool, later rents fall due on late payment (lease)
  probation_months       float
  collective_agreement   bool, a collective labour agreement is referenced
  notice_weeks           float, contractual notice period (employment)
  non_compete_years      float
"""

import re
from typing import Any

from .models import Clause, ExtractedFact
from .text_utils import searchable

FACTS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "lease": (
        "premises_kind",
        "monthly_rent",
        "deposit_amount",
        "deposit_months",
        "rent_increase_percent",
        "rent_increase_index",
        "eviction_undertaking",
        "late_payment_penalty",
        "acceleration_clause",
    ),
    "employment": (
        "probation_months",
        "collective_agreement",
        "notice_weeks",
        "non_compete_years",
    ),
}
NUMERIC_FACTS = {
    "monthly_rent",
    "deposit_amount",
    "deposit_months",
    "rent_increase_percent",
    "probation_months",
    "notice_weeks",
    "non_compete_years",
}
BOOLEAN_FACTS = {"late_payment_penalty", "acceleration_clause", "collective_agreement"}
ENUM_FACTS = {
    "premises_kind": {"residential", "workplace"},
    "rent_increase_index": {"tufe_12m_avg", "tufe", "ufe", "other"},
    "eviction_undertaking": {"with_contract", "after_handover", "unknown"},
}

_WORD_NUMBERS = {
    "bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7,
    "sekiz": 8, "dokuz": 9, "on": 10, "onbir": 11, "on bir": 11, "oniki": 12, "on iki": 12,
}
# Word numbers need a trailing word boundary so "onay" is not read as "on ay".
_NUM = r"(\d+(?:[.,]\d+)?|(?:on iki|on bir|oniki|onbir|bir|iki|uc|dort|bes|alti|yedi|sekiz|dokuz|on)\b)"
_MONEY_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)\s*(?:tl|try|turk lirasi|₺)")
_PERCENT_RE = re.compile(r"(?:%|yuzde)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:oraninda|%)")
_RESIDENTIAL_RE = re.compile(
    r"\b(?:konut\w*|mesken\w*|ev|evi|evin|evde|daire|dairedir|dairesi|dairenin|dairede|daireyi)\b"
)
_WORKPLACE_RE = re.compile(r"\b(?:isyeri\w*|dukkan\w*|ofis\w*|buro\w*|magaza\w*)\b")
# "icra dairesi", "vergi dairesi" are offices, not premises.
_OFFICE_NAMES_RE = re.compile(r"\b(?:icra|vergi|tapu)\s+daire\w*")
_DURATION_RE = re.compile(r"\b" + _NUM + r"\s*(?:\([^)]{1,15}\)\s*)?(yil|sene|hafta|is gunu|gun|ay)[a-z]*")


def parse_number(text: str) -> float | None:
    key = searchable(text).strip()
    if key in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[key])
    cleaned = key.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _durations(text: str) -> list[tuple[float, str]]:
    found = []
    for match in _DURATION_RE.finditer(text):
        number = parse_number(match.group(1))
        if number is not None:
            found.append((number, match.group(2)))
    return found


def _to_unit(value: float, unit: str, target: str) -> float:
    days = {"yil": 365.0, "sene": 365.0, "ay": 30.0, "hafta": 7.0, "gun": 1.0, "is gunu": 1.4}[unit]
    per_target = {"year": 365.0, "month": 30.0, "week": 7.0}[target]
    return round(value * days / per_target, 2)


def _first_money(text: str) -> float | None:
    match = _MONEY_RE.search(text)
    return parse_number(match.group(1)) if match else None


def _first_percent(text: str) -> float | None:
    match = _PERCENT_RE.search(text)
    if not match:
        return None
    return parse_number(match.group(1) or match.group(2))


def extract_facts_rule_based(clauses: list[Clause], contract_type: str | None) -> list[ExtractedFact]:
    """Regex extraction; one fact per name, from the first clause that states it."""
    wanted = FACTS_BY_TYPE.get(contract_type or "", ())
    facts: dict[str, ExtractedFact] = {}

    def put(name: str, value: Any, clause: Clause | None) -> None:
        if name in wanted and name not in facts and value is not None:
            facts[name] = ExtractedFact(name=name, value=value, clause_id=clause.id if clause else None)

    # Titles count too ("KONUT KİRA SÖZLEŞMESİ" may be the preamble's only signal).
    # Text is diacritic-free after searchable(), so "KONUT KIRA SOZLESMESI" from a
    # PDF matches the same way; Turkish suffixes are allowed ("konutun", "dairedir").
    whole = searchable(" ".join(f"{clause.title or ''} {clause.text}" for clause in clauses))
    premises_text = _OFFICE_NAMES_RE.sub(" ", whole)
    if _RESIDENTIAL_RE.search(premises_text):
        put("premises_kind", "residential", None)
    elif _WORKPLACE_RE.search(premises_text):
        put("premises_kind", "workplace", None)

    for clause in clauses:
        # The heading often carries the topic ("MADDE 5 - REKABET YASAĞI").
        text = searchable(f"{clause.title or ''} {clause.text}")
        if contract_type == "lease":
            _lease_facts(text, clause, put)
        elif contract_type == "employment":
            _employment_facts(text, clause, put)
    return list(facts.values())


def _lease_facts(text: str, clause: Clause, put) -> None:
    if "kira" in text and "aylik" in text and not re.search(r"depozito|guvence|teminat", text):
        put("monthly_rent", _first_money(text), clause)
    if re.search(r"depozito|guvence bedeli|guvence olarak|teminat", text):
        months = re.search(r"\b" + _NUM + r"\s*(?:\([^)]{1,15}\)\s*)?aylik kira", text)
        if months:
            put("deposit_months", parse_number(months.group(1)), clause)
        put("deposit_amount", _first_money(text), clause)
    if "kira" in text and re.search(r"artis|artir|artacak|arttir", text):
        if "tufe" in text or "tuketici fiyat" in text:
            index = "tufe_12m_avg" if re.search(r"12 aylik ortalama|on iki aylik ortalama|oniki aylik ortalama", text) else "tufe"
            put("rent_increase_index", index, clause)
        elif "ufe" in text or "uretici fiyat" in text:
            put("rent_increase_index", "ufe", clause)
        percent = _first_percent(text)
        if percent is not None:
            put("rent_increase_percent", percent, clause)
    if re.search(r"tahliye taahhut|tahliye taahhud|tahliye edecegini taahhut", text):
        if re.search(r"teslim(inden| tarihinden)? sonra", text):
            put("eviction_undertaking", "after_handover", clause)
        elif re.search(r"sozlesme ile birlikte|sozlesme tarihinde|imza tarihinde|ayni tarih|isbu sozlesme ile|imza sirasinda|taahhut eder", text):
            put("eviction_undertaking", "with_contract", clause)
        else:
            put("eviction_undertaking", "unknown", clause)
    late = re.search(r"gecikme|gec ode|zamaninda ode|odenmemesi|odenmezse|odemezse|odemedigi", text)
    if late and re.search(r"cezai sart|ceza", text):
        put("late_payment_penalty", True, clause)
    if "muaccel" in text or (
        late and re.search(r"(kalan|geri kalan|tum|butun) .{0,40}kira", text) and re.search(r"pesin|derhal|toplu", text)
    ):
        put("acceleration_clause", True, clause)


def _employment_facts(text: str, clause: Clause, put) -> None:
    if "toplu is sozlesmesi" in text:
        put("collective_agreement", True, clause)
    if "deneme sure" in text or "deneme kayd" in text:
        durations = _durations(text)
        if durations:
            value, unit = durations[0]
            put("probation_months", _to_unit(value, unit, "month"), clause)
    if "rekabet" in text:
        durations = [item for item in _durations(text) if item[1] in {"yil", "sene", "ay"}]
        if durations:
            value, unit = durations[0]
            put("non_compete_years", _to_unit(value, unit, "year"), clause)
    if re.search(r"bildirim sure|ihbar sure|ihbar onel|bildirim onel|onceden bildir", text):
        durations = [item for item in _durations(text) if item[1] in {"hafta", "gun", "is gunu", "ay"}]
        if durations:
            value, unit = durations[0]
            put("notice_weeks", _to_unit(value, unit, "week"), clause)


def coerce_fact_value(name: str, raw: Any) -> float | str | bool | None:
    """Validate one LLM-reported value; None when it does not fit the fact's type."""
    if raw is None:
        return None
    if name in NUMERIC_FACTS:
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        text = searchable(str(raw)).replace("%", "").replace("tl", "").strip()
        return parse_number(text.split()[0]) if text else None
    if name in BOOLEAN_FACTS:
        if isinstance(raw, bool):
            return raw
        key = searchable(str(raw)).strip()
        if key in {"true", "yes", "evet", "var", "1"}:
            return True
        if key in {"false", "no", "hayir", "yok", "0"}:
            return False
        return None
    if name in ENUM_FACTS:
        key = searchable(str(raw)).strip().replace(" ", "_")
        return key if key in ENUM_FACTS[name] else None
    return None


def merge_facts(primary: list[ExtractedFact], secondary: list[ExtractedFact]) -> list[ExtractedFact]:
    """Primary facts win; secondary facts only fill names the primary lacks."""
    names = {fact.name for fact in primary}
    return list(primary) + [fact for fact in secondary if fact.name not in names]
