"""Single source of truth for risk categories.

Owns the canonical category list, the alias map used to normalise model
output, the per-category relevance terms used by the keyword grader, and the
per-category fallback Yargı search queries.
"""

from .models import RiskFinding
from .text_utils import searchable

GENERAL_RISK = "general_risk"

CANONICAL_CATEGORIES: tuple[str, ...] = (
    "cash_payment",
    "deposit_forfeiture",
    "termination",
    "penalty_clause",
    "unlawful_entry",
    "eviction_undertaking",
    "rent_increase",
    "jurisdiction",
    "data_protection",
    "intellectual_property",
    "force_majeure",
    "payment_interest",
    "liability",
    "dispute_resolution",
    "probation_period",
    "non_compete",
    GENERAL_RISK,
)

# Keys are compared after `searchable()` and with "-"/"_" replaced by spaces.
CATEGORY_ALIASES: dict[str, str] = {
    "cash payment": "cash_payment",
    "payment": "cash_payment",
    "cash": "cash_payment",
    "elden odeme": "cash_payment",
    "deposit": "deposit_forfeiture",
    "deposit forfeiture": "deposit_forfeiture",
    "depozito": "deposit_forfeiture",
    "one sided rights": "unlawful_entry",
    "one sided right": "unlawful_entry",
    "unlawful entry": "unlawful_entry",
    "entry": "unlawful_entry",
    "eviction undertaking": "eviction_undertaking",
    "eviction": "eviction_undertaking",
    "tahliye taahhudu": "eviction_undertaking",
    "rent increase": "rent_increase",
    "increase": "rent_increase",
    "kira artisi": "rent_increase",
    "jurisdiction": "jurisdiction",
    "yetki": "jurisdiction",
    "termination": "termination",
    "fesih": "termination",
    "penalty clause": "penalty_clause",
    "penalty": "penalty_clause",
    "cezai sart": "penalty_clause",
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
    "late payment interest": "payment_interest",
    "gecikme faizi": "payment_interest",
    "liability": "liability",
    "limitation of liability": "liability",
    "indemnity": "liability",
    "sorumluluk": "liability",
    "probation": "probation_period",
    "probation period": "probation_period",
    "deneme suresi": "probation_period",
    "non compete": "non_compete",
    "noncompete": "non_compete",
    "rekabet yasagi": "non_compete",
    "general": GENERAL_RISK,
    "general risk": GENERAL_RISK,
    "other": GENERAL_RISK,
}

# Terms are matched after `searchable()` normalisation, so diacritics are optional.
# Every category except general_risk must have terms; avoid terms that appear in
# almost every court decision (e.g. "uyuşmazlık", "dava").
RELEVANCE_TERMS_BY_CATEGORY: dict[str, list[str]] = {
    "cash_payment": [
        "elden ödeme",
        "elden teslim",
        "nakit",
        "banka",
        "makbuz",
        "ödeme belgesi",
        "kira bedeli",
        "ödendiğinin ispatı",
        "yazılı delil",
    ],
    "deposit_forfeiture": [
        "depozito",
        "güvence bedeli",
        "iade edilmez",
        "iade edilmemesi",
        "kesinti",
        "teminat",
    ],
    "termination": [
        "fesih",
        "haklı neden",
        "derhal fesih",
        "sözleşmenin sona ermesi",
        "fesih hakkı",
        "sözleşmeyi sona erdirme",
        "hakli nedenle fesih",
        "ihbar süresi",
        "bildirimli fesih",
    ],
    "penalty_clause": [
        "cezai şart",
        "tbk",
        "türk borçlar kanunu",
        "indirim",
        "ceza koşulu",
        "muacceliyet",
        "fahiş ceza",
        "cezanın indirilmesi",
    ],
    "unlawful_entry": [
        "konut dokunulmazlığı",
        "konuta girme",
        "kiracının izni",
        "izinsiz giriş",
        "rızası olmadan",
        "özel hayat",
        "kiralananı gezdirme",
        "gezdirme",
        "kiralananın gösterilmesi",
    ],
    "eviction_undertaking": [
        "tahliye taahhüdü",
        "tahliye taahhütnamesi",
        "tahliye davası",
        "tahliye tarihi",
    ],
    "rent_increase": [
        "kira artışı",
        "yasal sınır",
        "artırım oranı",
        "tüfe",
        "kira bedeli",
        "kira tespit",
    ],
    "jurisdiction": [
        "yetkili mahkeme",
        "yetki sözleşmesi",
        "yetki itirazı",
        "kesin yetki",
        "taşınmazın bulunduğu yer",
        "tahkim şartı",
        "istac",
    ],
    "data_protection": [
        "kvkk",
        "veri işleyen",
        "veri sorumlusu",
        "kişisel veri",
        "kişisel verilerin korunması",
        "veri güvenliği",
        "veri ihlali",
        "aydınlatma yükümlülüğü",
        "açık rıza",
    ],
    "intellectual_property": [
        "fikri mülkiyet",
        "eser",
        "yazılım",
        "hak devri",
        "lisans",
        "telif hakkı",
        "fsek",
        "fikri haklar",
        "hakların devri",
        "kaynak kod",
    ],
    "force_majeure": [
        "mücbir sebep",
        "ifa imkansızlığı",
        "beklenmeyen hal",
        "beklenmeyen durum",
        "aşırı ifa güçlüğü",
        "sözleşmenin uyarlanması",
    ],
    "payment_interest": [
        "gecikme faizi",
        "temerrüt",
        "ticari faiz",
        "gecikme faiz oranı",
        "temerrüt faizi",
        "yasal faiz",
        "faiz istemi",
    ],
    "liability": [
        "sorumluluk sınırlaması",
        "sorumsuzluk anlaşması",
        "sorumluluğun sınırlandırılması",
        "ağır kusur",
        "hafif kusur",
        "tazminat",
        "kusur sorumluluğu",
        "zararın tazmini",
    ],
    "dispute_resolution": [
        "tahkim",
        "tahkim şartı",
        "hakem",
        "hakem heyeti",
        "istac",
        "arabuluculuk",
        "tahkim itirazı",
    ],
    "probation_period": [
        "deneme süresi",
        "deneme kaydı",
        "deneme süreli",
        "iki ay",
        "bildirimsiz fesih",
    ],
    "non_compete": [
        "rekabet yasağı",
        "rekabet etmeme",
        "rakip işletme",
        "hakkaniyete aykırı",
        "ekonomik gelecek",
        "rekabet yasağının sınırlandırılması",
    ],
}

FALLBACK_QUERIES_BY_CATEGORY: dict[str, str] = {
    "cash_payment": '"kira bedeli" "elden ödeme" "banka kanalı" ispat',
    "deposit_forfeiture": '"kira sözleşmesi" depozito "iade edilmez" tadilat',
    "termination": '"sözleşmenin feshi" "derhal fesih" "haklı neden"',
    "penalty_clause": '"cezai şart" "Türk Borçlar Kanunu" indirim',
    "unlawful_entry": '"kiracının izni" "konut dokunulmazlığı" konuta girme',
    "eviction_undertaking": '"tahliye taahhüdü" "kira sözleşmesi" "aynı tarih"',
    "rent_increase": '"konut kira sözleşmesi" "kira artışı" "yasal sınır"',
    "jurisdiction": '"yetkili mahkeme" "taşınmazın bulunduğu yer"',
    "data_protection": '"veri işleyen" KVKK "hizmet sözleşmesi"',
    "intellectual_property": '"fikri mülkiyet" "hak devri" yazılım',
    "force_majeure": '"mücbir sebep" "belirsiz hüküm" "hizmet sözleşmesi"',
    "payment_interest": '"gecikme faizi" "ticari sözleşme" oran',
    "liability": '"sorumluluk sınırlaması" "ağır kusur" tazminat',
    "dispute_resolution": '"tahkim şartı" ISTAC "hizmet sözleşmesi"',
    "probation_period": '"deneme süresi" "iş sözleşmesi" "iki ay"',
    "non_compete": '"rekabet yasağı" "iş sözleşmesi" süre',
    GENERAL_RISK: '"sözleşme hükmü" geçersizlik "Türk Borçlar Kanunu"',
}

# Contract-type specific fallback queries, used where the generic query names the
# wrong kind of contract (e.g. "hizmet sözleşmesi" for a lease termination).
FALLBACK_QUERIES_BY_TYPE: dict[tuple[str, str], str] = {
    ("termination", "service"): '"hizmet sözleşmesi" "derhal fesih" "haklı neden"',
    ("termination", "lease"):'"kira sözleşmesi" fesih "haklı neden" tahliye',
    ("termination", "employment"): '"iş sözleşmesi" "haklı nedenle fesih" "bildirim süresi"',
    ("force_majeure", "lease"): '"mücbir sebep" "kira sözleşmesi" uyarlama',
    ("force_majeure", "employment"): '"zorlayıcı sebep" "iş sözleşmesi" fesih',
    ("data_protection", "employment"): '"kişisel veri" "iş sözleşmesi" işveren KVKK',
    ("data_protection", "lease"): '"kişisel veri" "kira sözleşmesi" KVKK',
    ("dispute_resolution", "lease"): '"tahkim şartı" "kira sözleşmesi"',
    ("dispute_resolution", "employment"): '"tahkim şartı" "iş sözleşmesi" geçersiz',
    ("payment_interest", "lease"): '"kira bedeli" "gecikme faizi" temerrüt',
    ("penalty_clause", "lease"): '"kira sözleşmesi" "cezai şart" "geç ödeme"',
    ("penalty_clause", "employment"): '"iş sözleşmesi" "cezai şart" karşılıklılık',
    ("liability", "lease"): '"kiraya veren" sorumluluk "ayıplı kiralanan"',
    ("intellectual_property", "employment"): '"iş sözleşmesi" "fikri mülkiyet" eser işveren',
    ("cash_payment", "service"): '"hizmet bedeli" "elden ödeme" ispat',
    ("cash_payment", "employment"): '"ücret" "elden ödeme" "banka" ispat',
    ("jurisdiction", "employment"): '"iş mahkemesi" "yetki sözleşmesi" geçersiz',
    ("jurisdiction", "service"): '"yetki sözleşmesi" tacir "hizmet sözleşmesi"',
}

CATEGORY_LABELS_TR: dict[str, str] = {
    "cash_payment": "Elden ödeme",
    "deposit_forfeiture": "Güvence bedeli (depozito)",
    "termination": "Fesih",
    "penalty_clause": "Cezai şart",
    "unlawful_entry": "Kiralanana izinsiz giriş",
    "eviction_undertaking": "Tahliye taahhüdü",
    "rent_increase": "Kira artışı",
    "jurisdiction": "Yetkili mahkeme",
    "data_protection": "Kişisel verilerin korunması",
    "intellectual_property": "Fikri mülkiyet",
    "force_majeure": "Mücbir sebep",
    "payment_interest": "Gecikme faizi",
    "liability": "Sorumluluk",
    "dispute_resolution": "Uyuşmazlık çözümü",
    "probation_period": "Deneme süresi",
    "non_compete": "Rekabet yasağı",
    GENERAL_RISK: "Genel risk",
}

# Heuristics used to refine a generic category from the finding's own wording.
_REFINEMENT_TERMS: list[tuple[str, list[str]]] = [
    ("intellectual_property", ["fikri", "mulkiyet", "framework", "source code", "hak devri"]),
    ("force_majeure", ["mucbir", "force majeure", "olaganustu", "pandemi", "siber"]),
    ("dispute_resolution", ["tahkim", "arbitration", "istac"]),
    ("payment_interest", ["faiz", "interest", "gecikme"]),
]


def _check_registry() -> None:
    for category in CANONICAL_CATEGORIES:
        if category not in FALLBACK_QUERIES_BY_CATEGORY:
            raise RuntimeError(f"Missing fallback query for category {category}")
        if category != GENERAL_RISK and not RELEVANCE_TERMS_BY_CATEGORY.get(category):
            raise RuntimeError(f"Missing relevance terms for category {category}")
        if category not in CATEGORY_LABELS_TR:
            raise RuntimeError(f"Missing Turkish label for category {category}")
    for target in CATEGORY_ALIASES.values():
        if target not in CANONICAL_CATEGORIES:
            raise RuntimeError(f"Alias points at unknown category {target}")


_check_registry()


def allowed_categories_text() -> str:
    """Comma-separated canonical categories, for prompts."""
    return ", ".join(CANONICAL_CATEGORIES)


def canonicalize_risk_category(category: str) -> str:
    """Map free-form category text to a canonical category (general_risk if unknown)."""
    normalized = searchable(category).replace("-", " ").replace("_", " ").strip()
    underscored = "_".join(normalized.split())
    if underscored in CANONICAL_CATEGORIES:
        return underscored
    return CATEGORY_ALIASES.get(" ".join(normalized.split()), GENERAL_RISK)


def category_from_finding(finding: RiskFinding) -> str:
    """Canonical category, refined from the finding text when it is generic."""
    normalized_category = canonicalize_risk_category(finding.category)
    searchable_finding = searchable(
        " ".join([finding.category, finding.explanation, finding.recommendation])
    )
    if normalized_category == GENERAL_RISK:
        for target, terms in _REFINEMENT_TERMS:
            if any(term in searchable_finding for term in terms):
                return target
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


def category_label(category: str) -> str:
    return CATEGORY_LABELS_TR.get(category, category)


def relevance_terms(category: str | None) -> list[str]:
    if not category:
        return []
    return RELEVANCE_TERMS_BY_CATEGORY.get(category, [])


def fallback_query(category: str, contract_type: str | None = None) -> str:
    """Rule-based search query; type-specific where the generic one names another contract."""
    specific = FALLBACK_QUERIES_BY_TYPE.get((category, contract_type or ""))
    if specific:
        return specific
    return FALLBACK_QUERIES_BY_CATEGORY.get(category, FALLBACK_QUERIES_BY_CATEGORY[GENERAL_RISK])
