import json
import re
import unicodedata
from typing import Any, Protocol

from google import genai

from .config import Settings, settings
from .models import Clause, RiskFinding


class ContractAnalyzer(Protocol):
    async def summarize_contract(self, text: str, contract_type: str | None = None) -> str:
        ...

    async def segment_clauses(self, text: str) -> list[Clause]:
        ...

    async def classify_risks(
        self,
        clauses: list[Clause],
        contract_type: str | None = None,
    ) -> list[RiskFinding]:
        ...

    async def build_legal_queries(self, findings: list[RiskFinding]) -> list[str]:
        ...


def _searchable(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _json_array_from_text(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    elif "[" in cleaned and "]" in cleaned:
        cleaned = cleaned[cleaned.find("[") : cleaned.rfind("]") + 1]

    payload = json.loads(cleaned)
    if not isinstance(payload, list):
        raise ValueError("Gemini risk response must be a JSON array.")
    return [item for item in payload if isinstance(item, dict)]


def canonicalize_risk_category(category: str) -> str:
    normalized = _searchable(category).replace("-", " ").replace("_", " ")
    aliases = {
        "cash payment": "cash_payment",
        "payment": "cash_payment",
        "cash": "cash_payment",
        "deposit": "deposit_forfeiture",
        "deposit forfeiture": "deposit_forfeiture",
        "one sided rights": "unlawful_entry",
        "one sided right": "unlawful_entry",
        "unlawful entry": "unlawful_entry",
        "entry": "unlawful_entry",
        "eviction undertaking": "eviction_undertaking",
        "eviction": "eviction_undertaking",
        "rent increase": "rent_increase",
        "increase": "rent_increase",
        "jurisdiction": "jurisdiction",
        "termination": "termination",
        "penalty clause": "penalty_clause",
        "penalty": "penalty_clause",
        "data protection": "data_protection",
        "kvkk": "data_protection",
        "privacy": "data_protection",
        "intellectual property": "intellectual_property",
        "ip": "intellectual_property",
        "fikri mulkiyet": "intellectual_property",
        "force majeure": "force_majeure",
        "mucbir sebep": "force_majeure",
        "dispute resolution": "dispute_resolution",
        "arbitration": "dispute_resolution",
        "tahkim": "dispute_resolution",
        "default interest": "payment_interest",
        "delay interest": "payment_interest",
        "gecikme faizi": "payment_interest",
    }
    return aliases.get(normalized, normalized.replace(" ", "_"))


def category_from_finding(finding: RiskFinding) -> str:
    normalized_category = canonicalize_risk_category(finding.category)
    searchable_finding = _searchable(
        " ".join([finding.category, finding.explanation, finding.recommendation])
    )
    if normalized_category == "general_risk":
        if any(term in searchable_finding for term in ["fikri", "mulkiyet", "framework", "source code", "hak devri"]):
            return "intellectual_property"
        if any(term in searchable_finding for term in ["mucbir", "force majeure", "olaganustu", "pandemi", "siber"]):
            return "force_majeure"
        if any(term in searchable_finding for term in ["tahkim", "arbitration", "istac"]):
            return "dispute_resolution"
        if any(term in searchable_finding for term in ["faiz", "interest", "gecikme"]):
            return "payment_interest"
    if normalized_category == "cash_payment" and any(
        term in searchable_finding for term in ["faiz", "interest", "gecikme"]
    ):
        return "payment_interest"
    return normalized_category


def normalize_risk_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
    return [
        finding.model_copy(update={"category": category_from_finding(finding)})
        for finding in findings
    ]


class FakeContractAnalyzer:
    async def summarize_contract(self, text: str, contract_type: str | None = None) -> str:
        prefix = f"{contract_type} sozlesmesi" if contract_type else "Sozlesme"
        excerpt = text[:240].strip()
        return f"{prefix} icin MVP ozet: {excerpt}"

    async def segment_clauses(self, text: str) -> list[Clause]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        article_pattern = re.compile(r"^(?:MADDE|Madde|ARTICLE|Article)\s+\d+[^\n]*")
        clauses: list[Clause] = []
        current_title: str | None = None
        current_body: list[str] = []

        def flush() -> None:
            nonlocal current_title, current_body
            if current_title is None:
                current_body = []
                return
            body = " ".join(current_body).strip()
            clauses.append(
                Clause(
                    id=f"clause-{len(clauses) + 1}",
                    title=current_title,
                    text=body or current_title,
                )
            )
            current_title = None
            current_body = []

        for line in lines:
            if article_pattern.match(line):
                flush()
                current_title = line
                current_body = []
                continue
            if current_title is not None:
                current_body.append(line)

        flush()
        if clauses:
            return clauses

        return [
            Clause(id=f"clause-{index}", text=line)
            for index, line in enumerate(lines, start=1)
            if line
        ]

    async def classify_risks(
        self,
        clauses: list[Clause],
        contract_type: str | None = None,
    ) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        seen_categories: set[str] = set()

        def add(
            *,
            clause: Clause,
            category: str,
            severity: str,
            explanation: str,
            recommendation: str,
            confidence: float,
        ) -> None:
            if category in seen_categories:
                return
            seen_categories.add(category)
            findings.append(
                RiskFinding(
                    id=f"finding-{len(findings) + 1}",
                    category=category,
                    severity=severity,  # type: ignore[arg-type]
                    explanation=explanation,
                    recommendation=recommendation,
                    confidence=confidence,
                    clause_id=clause.id,
                )
            )

        for index, clause in enumerate(clauses):
            previous_text = clauses[index - 1].text if index > 0 else ""
            next_text = clauses[index + 1].text if index + 1 < len(clauses) else ""
            lowered = _searchable(" ".join([previous_text, clause.text, next_text]))

            if "elden" in lowered and ("odeme" in lowered or "kira bedeli" in lowered):
                add(
                    clause=clause,
                    category="cash_payment",
                    severity="medium",
                    explanation="Kira bedelinin elden odenmesi ispat ve mevzuata uyum riski dogurabilir.",
                    recommendation="Kira odemelerini banka kanaliyla ve aciklama bilgisiyle yapilacak sekilde duzenleyin.",
                    confidence=0.86,
                )
            if "tadilat" in lowered and "depozito" in lowered and "iade edilmez" in lowered:
                add(
                    clause=clause,
                    category="deposit_forfeiture",
                    severity="high",
                    explanation="Tadilat halinde depozitonun otomatik iade edilmemesi orantisiz yaptirim riski tasir.",
                    recommendation="Depozito kesintisini gercek zarar, belge ve mahsup prosedurune baglayin.",
                    confidence=0.9,
                )
            if ("fesih" in lowered or "feshedilir" in lowered or "terminate" in lowered) and (
                "derhal" in lowered or "tek taraf" in lowered or "unilateral" in lowered
            ):
                add(
                    clause=clause,
                    category="termination",
                    severity="high",
                    explanation="Derhal veya tek tarafli fesih hukmu manuel inceleme gerektirir.",
                    recommendation="Fesih sebeplerini, bildirim suresini ve telafi hakkini netlestirin.",
                    confidence=0.9,
                )
            elif "fesih" in lowered or "terminate" in lowered:
                add(
                    clause=clause,
                    category="termination",
                    severity="medium",
                    explanation="Fesih hukmu taraf dengesi ve bildirim kosullari acisindan incelenmelidir.",
                    recommendation="Fesih prosedurunu, sureleri ve sonuclari acik hale getirin.",
                    confidence=0.72,
                )
            if "cezai sart" in lowered or "penalty" in lowered:
                add(
                    clause=clause,
                    category="penalty_clause",
                    severity="medium",
                    explanation="Cezai sart/penalty hukmu orantililik acisindan incelenmelidir.",
                    recommendation="Cezai sart tutarini, ust siniri ve uygulanma kosullarini kontrol edin.",
                    confidence=0.85,
                )
            if (
                "izni olmaksizin" in lowered or "izin olmaksizin" in lowered
            ) and ("tasinmaza" in lowered or "daire" in lowered or "konut" in lowered):
                add(
                    clause=clause,
                    category="unlawful_entry",
                    severity="critical",
                    explanation="Kiracinin izni olmadan konuta giris hakki konut dokunulmazligi ve ozel hayat riski dogurur.",
                    recommendation="Giris hakkini onceden bildirim, makul saat ve kiraci onayi sartlarina baglayin.",
                    confidence=0.95,
                )
            if "tahliye taahhudu" in lowered or "tahliye taahhut" in lowered:
                add(
                    clause=clause,
                    category="eviction_undertaking",
                    severity="high",
                    explanation="Tahliye taahhudunun sozlesme ile birlikte alinmasi gecerlilik tartismasi yaratabilir.",
                    recommendation="Tahliye taahhudunu sozlesme tarihinden sonra, serbest iradeyi gosterecek sekilde ayri degerlendirin.",
                    confidence=0.88,
                )
            if ("%100" in lowered or "100 oraninda" in lowered) and (
                "artir" in lowered or "kira bedeli" in lowered
            ):
                add(
                    clause=clause,
                    category="rent_increase",
                    severity="high",
                    explanation="Yillik %100 kira artisi yasal artis sinirlariyla uyumsuz olabilir.",
                    recommendation="Artis oranini uygulanabilir yasal sinir ve endekslerle uyumlu hale getirin.",
                    confidence=0.92,
                )
            if "ankara mahkemeleri" in lowered and (
                "istanbul" in lowered or contract_type == "lease"
            ):
                add(
                    clause=clause,
                    category="jurisdiction",
                    severity="medium",
                    explanation="Tasinmaz Istanbul'dayken Ankara mahkemelerinin yetkili secilmesi yetki itirazi riski yaratabilir.",
                    recommendation="Yetki maddesini tasinmazin bulundugu yer ve zorunlu yetki kurallari acisindan kontrol edin.",
                    confidence=0.76,
                )
        return findings

    async def build_legal_queries(self, findings: list[RiskFinding]) -> list[str]:
        queries: list[str] = []
        for finding in findings:
            normalized_category = category_from_finding(finding)

            query_by_category = {
                "cash_payment": '"kira bedeli" "elden ödeme" "banka kanalı" ispat',
                "deposit_forfeiture": '"kira sözleşmesi" depozito "iade edilmez" tadilat',
                "termination": '"hizmet sözleşmesi" "derhal fesih" "haklı neden"',
                "penalty_clause": '"cezai şart" "Türk Borçlar Kanunu" indirim',
                "unlawful_entry": '"kiracinin izni olmadan" konuta girme',
                "eviction_undertaking": '"tahliye taahhüdü" "kira sözleşmesi" "aynı tarih"',
                "rent_increase": '"konut kira sözleşmesi" "kira artışı" "yasal sınır"',
                "jurisdiction": '"yetkili mahkeme" "taşınmazın bulunduğu yer"',
                "data_protection": '"veri işleyen" KVKK "hizmet sözleşmesi"',
                "intellectual_property": '"fikri mülkiyet" "hak devri" yazılım',
                "force_majeure": '"mücbir sebep" "belirsiz hüküm" "hizmet sözleşmesi"',
                "dispute_resolution": '"tahkim şartı" ISTAC "hizmet sözleşmesi"',
                "payment_interest": '"gecikme faizi" "ticari sözleşme" oran',
            }
            queries.append(
                query_by_category.get(
                    normalized_category,
                    f"hizmet sozlesmesi {finding.category} riski yargi karari",
                )
            )
        return list(dict.fromkeys(queries))


class GeminiContractAnalyzer:
    def __init__(self, app_settings: Settings = settings) -> None:
        if not app_settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiContractAnalyzer.")
        self._settings = app_settings
        self._client = genai.Client(api_key=app_settings.gemini_api_key)
        self._fallback = FakeContractAnalyzer()

    async def summarize_contract(self, text: str, contract_type: str | None = None) -> str:
        prompt = (
            "Summarize this contract in Turkish for a legal reviewer. "
            "Use 120-180 words and at most 5 bullets. "
            "Identify only the contract purpose, parties, duration, price, payment, IP, termination, "
            "and dispute resolution if present. "
            "Do not include risk analysis, recommendations, case law, or repeated findings.\n\n"
        )
        if contract_type:
            prompt += f"Contract type: {contract_type}\n\n"
        prompt += text[:6000]

        response = await self._client.aio.models.generate_content(
            model=self._settings.gemini_model,
            contents=prompt,
        )
        return (response.text or "").strip() or "Ozet uretilemedi."

    async def segment_clauses(self, text: str) -> list[Clause]:
        return await self._fallback.segment_clauses(text)

    async def classify_risks(
        self,
        clauses: list[Clause],
        contract_type: str | None = None,
    ) -> list[RiskFinding]:
        clause_payload = "\n".join(f"{clause.id}: {clause.text}" for clause in clauses)
        prompt = (
            "You are reviewing a Turkish contract for legal and procurement risk. "
            "Return ONLY a JSON array. Do not wrap it in markdown. Each item must have: "
            "category, severity, explanation, recommendation, confidence, clause_id. "
            "Return at most 6 findings. Prefer material legal risks only. "
            "Keep explanation under 240 characters and recommendation under 240 characters. "
            "Write the explanation and recommendation fields in Turkish. "
            "category must be one of cash_payment, deposit_forfeiture, termination, penalty_clause, "
            "unlawful_entry, eviction_undertaking, rent_increase, jurisdiction, data_protection, "
            "intellectual_property, force_majeure, payment_interest, "
            "liability, dispute_resolution, general_risk. "
            "severity must be one of low, medium, high, critical. confidence must be 0..1. "
            "Do not invent law numbers, article numbers, court names, or case numbers. "
            "Mention specific statutes or cases only if they appear in the clause text. "
            "Focus on enforceability, statutory limits, one-sided rights, privacy, payment, "
            "termination, deposit, eviction undertaking, rent increase, jurisdiction, data protection, "
            "penalty clauses, liability and dispute resolution risks.\n\n"
        )
        if contract_type:
            prompt += f"Contract type: {contract_type}\n\n"
        prompt += f"Clauses:\n{clause_payload[:8000]}"

        try:
            response = await self._client.aio.models.generate_content(
                model=self._settings.gemini_model,
                contents=prompt,
            )
            parsed = _json_array_from_text(response.text or "[]")
            findings: list[RiskFinding] = []
            valid_clause_ids = {clause.id for clause in clauses}
            for item in parsed:
                clause_id = item.get("clause_id")
                if clause_id not in valid_clause_ids:
                    clause_id = None
                findings.append(
                    RiskFinding(
                        id=f"finding-{len(findings) + 1}",
                        category=canonicalize_risk_category(str(item.get("category", "general_risk"))),
                        severity=item.get("severity", "medium"),
                        explanation=str(item.get("explanation", "Risk requires legal review.")),
                        recommendation=str(item.get("recommendation", "Review and revise the clause.")),
                        confidence=float(item.get("confidence", 0.7)),
                        clause_id=clause_id,
                    )
                )
            if findings:
                return normalize_risk_findings(findings)
        except Exception:
            pass

        return normalize_risk_findings(await self._fallback.classify_risks(clauses, contract_type))

    async def build_legal_queries(self, findings: list[RiskFinding]) -> list[str]:
        if not findings:
            return []
        queries: list[str] = []
        for finding in findings:
            prompt = (
                "You are an expert Turkish legal researcher. "
                "Based on the following contract risk finding, generate a single optimized search query "
                "to find relevant Turkish Court of Cassation (Yargıtay), Council of State (Danıştay), "
                "or KVKK decisions on a legal database.\n\n"
                "Follow these constraints:\n"
                "1. The query must be in Turkish.\n"
                "2. Use exact match double quotes for key legal concepts (e.g. \"cezai şart\", \"veri işleyen\").\n"
                "3. Keep the query under 10 words.\n"
                "4. Return ONLY the search query text, no explanation, no quotes around the whole query.\n\n"
                f"Risk Category: {finding.category}\n"
                f"Explanation: {finding.explanation}\n"
                f"Recommendation: {finding.recommendation}\n"
            )
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._settings.gemini_model,
                    contents=prompt,
                )
                query = (response.text or "").strip().strip('"')
                if query:
                    queries.append(query)
            except Exception:
                fallback_queries = await self._fallback.build_legal_queries([finding])
                queries.extend(fallback_queries)
        return list(dict.fromkeys(queries))
