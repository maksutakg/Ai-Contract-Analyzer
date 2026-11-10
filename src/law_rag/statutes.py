"""Curated statute provisions and the category -> provision mapping.

Every provision here was checked against the consolidated text published on
mevzuat.gov.tr (MevzuatMetin PDFs, retrieved 2026-11-10). The summaries are
short Turkish paraphrases, not quotations. The LLM never produces a law or
article number; findings get references only from this module.

Not included because no single verified provision fits: cash_payment (the bank
payment duty for rent comes from tax communiqués, not a statute article) and
general_risk.
"""

from .contract_types import OTHER
from .models import LegalReference, RiskFinding

_TBK_URL = "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6098&MevzuatTur=1&MevzuatTertip=5"
_IK_URL = "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=4857&MevzuatTur=1&MevzuatTertip=5"
_HMK_URL = "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6100&MevzuatTur=1&MevzuatTertip=5"
_KVKK_URL = "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6698&MevzuatTur=1&MevzuatTertip=5"
_FSEK_URL = "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=5846&MevzuatTur=1&MevzuatTertip=3"

_TBK = ("Türk Borçlar Kanunu", "6098", _TBK_URL)
_IK = ("İş Kanunu", "4857", _IK_URL)
_HMK = ("Hukuk Muhakemeleri Kanunu", "6100", _HMK_URL)
_KVKK = ("Kişisel Verilerin Korunması Kanunu", "6698", _KVKK_URL)
_FSEK = ("Fikir ve Sanat Eserleri Kanunu", "5846", _FSEK_URL)


def _ref(law: tuple[str, str, str], article: str, summary: str) -> LegalReference:
    name, number, url = law
    return LegalReference(law_name=name, law_number=number, article=article, summary=summary, url=url)


PROVISIONS: dict[str, LegalReference] = {
    "tbk_182": _ref(_TBK, "m.182", "Taraflar ceza koşulunun miktarını serbestçe belirleyebilir; ancak hâkim aşırı gördüğü cezayı kendiliğinden indirir."),
    "tbk_115": _ref(_TBK, "m.115", "Borçlunun ağır kusurundan sorumlu olmayacağına dair önceden yapılan anlaşma kesin olarak hükümsüzdür."),
    "tbk_120": _ref(_TBK, "m.120", "Sözleşmeyle kararlaştırılan yıllık temerrüt faizi, mevzuattaki yıllık faiz oranının yüzde yüz fazlasını aşamaz."),
    "tbk_136": _ref(_TBK, "m.136", "Borcun ifası borçlunun sorumlu tutulamayacağı sebeplerle imkânsızlaşırsa borç sona erer."),
    "tbk_138": _ref(_TBK, "m.138", "Öngörülemeyen olağanüstü bir durum ifayı borçlu aleyhine aşırı ölçüde değiştirirse borçlu sözleşmenin uyarlanmasını, olmazsa dönme veya feshi isteyebilir."),
    "tbk_319": _ref(_TBK, "m.319", "Kiracı, bakım, satış veya yeniden kiralama için zorunlu ölçüde kiralananın gezilip görülmesine izin verir; kiraya veren bunu uygun süre önce bildirmek ve kiracının yararını gözetmek zorundadır."),
    "tbk_342": _ref(_TBK, "m.342", "Konut ve çatılı işyeri kiralarında kiracıdan alınacak güvence üç aylık kira bedelini aşamaz; para güvencesi vadeli bir tasarruf hesabına yatırılır."),
    "tbk_344": _ref(_TBK, "m.344", "Yenilenen kira dönemleri için kira artışına ilişkin anlaşmalar, bir önceki kira yılında TÜFE'deki on iki aylık ortalamalara göre değişim oranını geçmemek koşuluyla geçerlidir."),
    "tbk_346": _ref(_TBK, "m.346", "Kiracıya kira bedeli ve yan giderler dışında ödeme yükümlülüğü getirilemez; kiranın geç ödenmesine ceza koşulu veya sonraki kiraların muaccel olacağı anlaşmaları geçersizdir."),
    "tbk_347": _ref(_TBK, "m.347", "Konut ve çatılı işyeri kiralarında kiraya veren, sözleşme süresinin bitimine dayanarak sözleşmeyi sona erdiremez; kiracı bildirimde bulunmazsa sözleşme bir yıl uzar."),
    "tbk_352": _ref(_TBK, "m.352/1", "Kiracının kiralananı belli bir tarihte boşaltmayı yazılı olarak üstlenmesi, kiralananın tesliminden sonra verilmiş olmalıdır; aksi hâlde tahliye taahhüdüne dayanılamaz."),
    "tbk_444": _ref(_TBK, "m.444", "İşçinin rekabet yasağı yazılı olmalı ve ancak işçinin müşteri çevresi veya üretim sırları hakkında bilgi edinebildiği hâllerde geçerlidir."),
    "tbk_445": _ref(_TBK, "m.445", "Rekabet yasağı yer, zaman ve iş türü bakımından işçinin ekonomik geleceğini hakkaniyete aykırı tehlikeye düşüremez; süresi özel durumlar dışında iki yılı aşamaz."),
    "ik_15": _ref(_IK, "m.15", "İş sözleşmesine konulan deneme süresi en çok iki aydır; toplu iş sözleşmesiyle dört aya kadar uzatılabilir."),
    "ik_17": _ref(_IK, "m.17", "Belirsiz süreli iş sözleşmesinin feshinde bildirim süreleri kıdeme göre iki, dört, altı ve sekiz haftadır; bu süreler asgaridir."),
    "hmk_17": _ref(_HMK, "m.17", "Tacirler veya kamu tüzel kişileri, aralarındaki uyuşmazlıklar için sözleşmeyle bir veya birden fazla mahkemeyi yetkili kılabilir (yetki sözleşmesi)."),
    "hmk_18": _ref(_HMK, "m.18", "Kesin yetki hâllerinde yetki sözleşmesi yapılamaz; geçerli yetki sözleşmesi yazılı olmalı ve yetkili mahkemeyi göstermelidir."),
    "hmk_412": _ref(_HMK, "m.412", "Tahkim sözleşmesi, uyuşmazlıkların hakem veya hakem kuruluna bırakılmasına ilişkin yazılı anlaşmadır; sözleşmenin bir şartı olarak da yapılabilir."),
    "kvkk_5": _ref(_KVKK, "m.5", "Kişisel veriler kural olarak ilgili kişinin açık rızası olmadan işlenemez; kanunda sayılan istisnalar saklıdır."),
    "kvkk_12": _ref(_KVKK, "m.12", "Veri sorumlusu veri güvenliği için gerekli teknik ve idari tedbirleri almak zorundadır; verileri kendi adına işleyen kişilerle birlikte müştereken sorumludur."),
    "fsek_18": _ref(_FSEK, "m.18", "Aksi kararlaştırılmadıkça işçi ve hizmetlilerin işlerini görürken meydana getirdikleri eserler üzerindeki mali haklar işverence kullanılır."),
    "fsek_52": _ref(_FSEK, "m.52", "Mali haklara ilişkin sözleşme ve tasarrufların yazılı olması ve devredilen hakların ayrı ayrı gösterilmesi şarttır."),
}

# category -> contract type (or "*" for any type) -> provision keys.
_CATEGORY_PROVISIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "deposit_forfeiture": {"lease": ("tbk_342",)},
    "rent_increase": {"lease": ("tbk_344",)},
    "penalty_clause": {"lease": ("tbk_346", "tbk_182"), "*": ("tbk_182",)},
    "eviction_undertaking": {"lease": ("tbk_352",), "*": ("tbk_352",)},
    "unlawful_entry": {"lease": ("tbk_319",), "*": ("tbk_319",)},
    "termination": {"lease": ("tbk_347",), "employment": ("ik_17",)},
    "payment_interest": {"lease": ("tbk_346", "tbk_120"), "*": ("tbk_120",)},
    "liability": {"*": ("tbk_115",)},
    "force_majeure": {"*": ("tbk_136", "tbk_138")},
    "jurisdiction": {"*": ("hmk_17", "hmk_18")},
    "dispute_resolution": {"*": ("hmk_412",)},
    "data_protection": {"employment": ("kvkk_5", "kvkk_12"), "*": ("kvkk_12",)},
    "intellectual_property": {"employment": ("fsek_18", "fsek_52"), "*": ("fsek_52",)},
    "probation_period": {"*": ("ik_15",)},
    "non_compete": {"*": ("tbk_444", "tbk_445")},
}


def provision(key: str) -> LegalReference:
    return PROVISIONS[key].model_copy()


def references_for(category: str, contract_type: str | None) -> list[LegalReference]:
    by_type = _CATEGORY_PROVISIONS.get(category, {})
    keys = by_type.get(contract_type or OTHER) or by_type.get("*") or ()
    return [provision(key) for key in keys]


def ground_findings(findings: list[RiskFinding], contract_type: str | None) -> list[RiskFinding]:
    """Attach curated statute references to each finding (keeps existing ones first)."""
    grounded: list[RiskFinding] = []
    for finding in findings:
        references = list(finding.legal_references)
        seen = {(ref.law_number, ref.article) for ref in references}
        for ref in references_for(finding.category, contract_type):
            if (ref.law_number, ref.article) not in seen:
                seen.add((ref.law_number, ref.article))
                references.append(ref)
        grounded.append(finding.model_copy(update={"legal_references": references}))
    return grounded
