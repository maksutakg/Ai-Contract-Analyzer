"""Missing clause detection: curated checklist per contract type.

The analyzer decides which topics are present (the LLM in one call; keywords
offline or on failure). This module owns the checklist and turns the presence
map into report entries. Missing clauses do not change the risk score.
"""

from dataclasses import dataclass

from .contract_types import BOTH, role_label
from .models import Clause, MissingClause, TopicPresence
from .text_utils import searchable

_LOWER = {"high": "medium", "medium": "low", "low": "low"}


@dataclass(frozen=True)
class ChecklistTopic:
    id: str
    title: str
    importance: str
    hurts: str  # role id most exposed by the absence, or "both"
    keywords: tuple[str, ...]  # matched after searchable()
    why: str
    suggestion: str


def _t(id, title, importance, hurts, keywords, why, suggestion) -> ChecklistTopic:
    return ChecklistTopic(id, title, importance, hurts, tuple(keywords), why, suggestion)


_DISPUTE = _t(
    "dispute_resolution", "Uyuşmazlık çözümü ve yetkili mahkeme", "medium", BOTH,
    ["yetkili mahkeme", "mahkemeleri", "icra daireleri", "tahkim", "arabulucu", "uyusmazlik"],
    "Yetkili mahkeme veya çözüm yolu belirlenmemişse uyuşmazlıkta genel yetki kuralları uygulanır ve süreç öngörülemez hâle gelebilir.",
    "Bu sözleşmeden doğan uyuşmazlıklarda, kanunun zorunlu yetki kuralları saklı kalmak üzere ... mahkemeleri ve icra daireleri yetkilidir.",
)
_TERMINATION = _t(
    "termination_notice", "Fesih ve bildirim süresi", "high", BOTH,
    ["fesih", "feshet", "sona erme", "sona erdir", "bildirim suresi", "ihbar"],
    "Fesih koşulları ve bildirim süresi yazılmamışsa sözleşmeden çıkış belirsizleşir ve haksız fesih tartışması doğabilir.",
    "Taraflardan her biri, en az 30 gün önceden yazılı bildirimde bulunarak sözleşmeyi feshedebilir. Haklı nedenle fesih hâlinde fesih sebebi bildirimde açıkça belirtilir.",
)
_PERSONAL_DATA = _t(
    "personal_data", "Kişisel verilerin korunması", "high", BOTH,
    ["kisisel veri", "kvkk", "6698", "veri sorumlusu", "veri isleyen", "gizlilik ve veri"],
    "Kişisel veri işlenecekse rol dağılımı ve güvenlik yükümlülükleri yazılmamışsa veri ihlalinde sorumluluk paylaşımı belirsiz kalır.",
    "Taraflar, sözleşme kapsamında işlenen kişisel veriler bakımından 6698 sayılı Kanun'a uygun davranır; veri güvenliği için gerekli teknik ve idari tedbirleri alır ve bir veri ihlalini öğrendiğinde diğer tarafa gecikmeksizin bildirir.",
)
_CONFIDENTIALITY = _t(
    "confidentiality", "Gizlilik", "medium", BOTH,
    ["gizlilik", "gizli bilgi", "sir saklama", "ticari sir", "ifsa"],
    "Gizlilik yükümlülüğü yoksa paylaşılan ticari bilgilerin üçüncü kişilere açıklanmasını sözleşmeye dayanarak engellemek zorlaşır.",
    "Taraflar, sözleşme nedeniyle öğrendikleri ticari sır ve gizli bilgileri sözleşme süresince ve sona ermesinden sonra iki yıl boyunca üçüncü kişilere açıklamaz.",
)

CHECKLISTS: dict[str, tuple[ChecklistTopic, ...]] = {
    "lease": (
        _t("rent_payment", "Kira bedeli ve ödeme şekli", "high", BOTH,
           ["kira bedeli", "aylik kira", "kira tutari"],
           "Kira bedeli, ödeme günü ve yöntemi açık değilse temerrüt ve ispat tartışması doğar.",
           "Aylık kira bedeli ... TL olup her ayın ...'ine kadar kiraya verenin ... IBAN numaralı banka hesabına, açıklama kısmında dönem belirtilerek ödenir."),
        _t("term", "Kira süresi", "high", BOTH,
           ["kira suresi", "sure ile", "yil sureli", "baslangic tarihi", "sozlesmenin suresi"],
           "Süre belirtilmemişse sözleşme belirsiz süreli sayılabilir ve fesih dönemleri buna göre değişir.",
           "Kira süresi ... tarihinden başlamak üzere bir yıldır."),
        _t("deposit", "Güvence bedeli (depozito)", "medium", "tenant",
           ["depozito", "guvence bedeli", "teminat"],
           "Güvence bedelinin tutarı ve iade koşulları yazılmamışsa sözleşme sonunda iade ve kesinti uyuşmazlığı çıkar.",
           "Kiracı, üç aylık kira bedelini aşmamak üzere ... TL güvence bedeli verir; bedel vadeli bir tasarruf hesabına yatırılır ve tahliyede belgelenmiş hasarlar mahsup edildikten sonra iade edilir."),
        _t("rent_increase", "Kira artışı", "medium", "landlord",
           ["artis", "artir", "tufe", "kira tespit"],
           "Artış hükmü yoksa yenilenen dönemlerde kira bedeli ancak anlaşma veya dava yoluyla değiştirilebilir.",
           "Yenilenen kira dönemlerinde kira bedeli, bir önceki kira yılında TÜFE'nin on iki aylık ortalamalara göre değişim oranında artırılır."),
        _t("maintenance_repairs", "Bakım, onarım ve ayıplar", "medium", BOTH,
           ["bakim", "onarim", "tamir", "ayip", "hasar"],
           "Bakım ve onarım paylaşımı belirsizse masrafların kime ait olduğu konusunda uyuşmazlık çıkar.",
           "Kiralananın olağan kullanımı için gereken küçük temizlik ve bakım giderleri kiracıya, esaslı onarımlar ve ayıpların giderilmesi kiraya verene aittir."),
        _t("utilities", "Yan giderler ve aidat", "low", "tenant",
           ["aidat", "elektrik", "su ", "dogalgaz", "yan gider", "isitma"],
           "Aidat ve kullanma giderlerinin kime ait olduğu yazılmamışsa her dönem tartışma konusu olabilir.",
           "Isıtma, aydınlatma, su ve olağan yönetim aidatı kiracıya; demirbaş ve esaslı yönetim giderleri kiraya verene aittir."),
        _t("subletting", "Alt kira ve devir", "low", "landlord",
           ["alt kira", "baskasina kiralayamaz", "devredemez", "kullanim hakkini"],
           "Alt kira ve devir yasağı düzenlenmemişse kiracının kiralananı başkasına kullandırması tartışmalı hâle gelir.",
           "Kiracı, kiraya verenin yazılı izni olmadıkça kiralananı başkasına kiralayamaz ve kullanım hakkını devredemez."),
        _t("handover", "Teslim ve tahliyede durum tespiti", "medium", "tenant",
           ["teslim", "tahliye", "demirbas", "durum tespit"],
           "Teslim anındaki durum belgelenmemişse tahliyede hasar iddialarına karşı ispat güçleşir.",
           "Kiralanan, ekteki durum tespit tutanağı ve fotoğraflarla teslim edilir; tahliyede aynı tutanak esas alınır."),
        _DISPUTE,
    ),
    "service": (
        _t("scope", "Hizmetin kapsamı", "high", BOTH,
           ["konusu", "kapsam", "hizmetin tanimi", "is tanimi", "teslim edilecek"],
           "Kapsam açık değilse hangi işin eksik veya ek iş sayılacağı tartışmalı olur.",
           "Hizmetin kapsamı, teslimatlar ve kabul kriterleri Ek-1'de ayrıntılı olarak gösterilmiştir; kapsam dışı talepler yazılı ek protokolle belirlenir."),
        _t("fee_payment", "Bedel ve ödeme koşulları", "high", "provider",
           ["bedel", "ucret", "odeme", "fatura"],
           "Bedel ve ödeme takvimi yoksa alacağın muacceliyeti ve temerrüt tarihi belirsizleşir.",
           "Hizmet bedeli ... TL + KDV olup faturanın tebliğinden itibaren 30 gün içinde ödenir."),
        _t("term", "Sözleşme süresi", "medium", BOTH,
           ["sozlesmenin suresi", "sure ile", "yururluk", "baslangic tarihi", "yil sureli", "ay sureli"],
           "Süre belirtilmemişse sözleşmenin ne zaman sona ereceği ve yenilenip yenilenmeyeceği belirsizdir.",
           "Sözleşme imza tarihinde yürürlüğe girer ve bir yıl süreyle geçerlidir; taraflar yazılı olarak uzatabilir."),
        _TERMINATION,
        _CONFIDENTIALITY,
        _PERSONAL_DATA,
        _t("ip_ownership", "Fikri mülkiyet hakları", "high", "client",
           ["fikri mulkiyet", "telif", "mali hak", "lisans", "kaynak kod", "eser"],
           "Ortaya çıkan işlerin hakları yazılı ve ayrı ayrı devredilmemişse hizmet alan, teslim edilen işi serbestçe kullanamayabilir.",
           "Hizmet kapsamında üretilen eserler üzerindeki çoğaltma, yayma, işleme, temsil ve umuma iletim hakları, bedelin ödenmesiyle süre ve yer sınırı olmaksızın hizmet alana devredilir."),
        _t("liability_cap", "Sorumluluk sınırı", "medium", "provider",
           ["sorumluluk", "tazminat", "zarar"],
           "Sorumluluk sınırı yoksa taraflar, öngörülmeyen dolaylı zararlar için de sınırsız sorumlu tutulabilir.",
           "Tarafların bu sözleşmeden doğan toplam sorumluluğu, kast ve ağır kusur hâlleri hariç, son 12 ayda ödenen hizmet bedeliyle sınırlıdır."),
        _t("force_majeure", "Mücbir sebep", "low", BOTH,
           ["mucbir sebep", "force majeure", "olaganustu durum"],
           "Mücbir sebep düzenlenmemişse ifa engellerinde sorumluluk ve fesih hakkı yalnızca genel hükümlere kalır.",
           "Doğal afet, salgın, savaş ve resmi makam kararları gibi tarafların kontrolü dışındaki olaylar mücbir sebeptir; süre 60 günü aşarsa taraflar sözleşmeyi feshedebilir."),
        _DISPUTE,
    ),
    "employment": (
        _t("job_description", "Görev tanımı", "medium", "employee",
           ["gorev", "pozisyon", "unvan", "is tanimi"],
           "Görev tanımı yoksa işçiye esaslı olarak farklı işler verilmesi tartışmalı hâle gelir.",
           "İşçi, ... pozisyonunda Ek-1'deki görev tanımına uygun olarak çalışır."),
        _t("wage", "Ücret ve ödeme zamanı", "high", "employee",
           ["ucret", "maas", "brut", "net"],
           "Ücret ve ödeme günü yazılmamışsa alacakların ispatı zorlaşır.",
           "İşçiye aylık brüt ... TL ücret, her ayın en geç ...'inde banka hesabına ödenir."),
        _t("working_hours", "Çalışma süresi", "medium", "employee",
           ["calisma suresi", "calisma saat", "haftalik", "fazla calisma", "mesai"],
           "Çalışma süresi ve fazla çalışma düzeni belirtilmemişse fazla mesai alacakları tartışmalı olur.",
           "Haftalık çalışma süresi 45 saattir; fazla çalışma işçinin onayı ve kanuni zamlı ücretle yapılır."),
        _t("workplace", "İşyeri", "low", "employee",
           ["isyeri", "calisma yeri", "adres"],
           "İşyeri belirtilmemişse işyeri değişikliğinin esaslı değişiklik olup olmadığı tartışmalı olur.",
           "İşçinin çalışma yeri ... adresindeki işyeridir."),
        _t("term_type", "Sözleşmenin süresi (belirli / belirsiz)", "medium", BOTH,
           ["belirsiz sureli", "belirli sureli", "sozlesmenin suresi"],
           "Sözleşmenin belirli veya belirsiz süreli olduğu yazılmamışsa fesih ve tazminat hakları belirsizleşir.",
           "Bu iş sözleşmesi belirsiz sürelidir."),
        _t("annual_leave", "Yıllık izin", "low", "employee",
           ["yillik izin", "ucretli izin"],
           "Yıllık izin düzeni yoksa izin kullanımı ve ücreti konusunda uyuşmazlık çıkabilir.",
           "İşçi, kıdemine göre kanunda öngörülen sürelerden az olmamak üzere yıllık ücretli izin kullanır."),
        _TERMINATION,
        _CONFIDENTIALITY,
        _PERSONAL_DATA,
    ),
}
CHECKLISTS["other"] = (
    _t("subject", "Sözleşmenin konusu", "high", BOTH,
       ["konusu", "amac", "kapsam"],
       "Sözleşmenin konusu açık değilse tarafların edimleri belirsiz kalır.",
       "Bu sözleşmenin konusu, ...'dır."),
    _t("price_payment", "Bedel ve ödeme", "medium", BOTH,
       ["bedel", "ucret", "odeme"],
       "Bedel ve ödeme koşulları yazılmamışsa temerrüt ve ispat tartışması doğar.",
       "Sözleşme bedeli ... TL olup ... tarihinde banka havalesiyle ödenir."),
    _TERMINATION,
    _DISPUTE,
)


def tr_capitalize(text: str) -> str:
    """Capitalise with Turkish dotted/dotless i rules ("işçi" -> "İşçi")."""
    if not text:
        return text
    first = {"i": "İ", "ı": "I"}.get(text[0], text[0].upper())
    return first + text[1:]


def checklist_for(contract_type: str | None) -> tuple[ChecklistTopic, ...]:
    return CHECKLISTS.get(contract_type or "other", CHECKLISTS["other"])


def keyword_presence(clauses: list[Clause], contract_type: str | None) -> dict[str, TopicPresence]:
    haystack = searchable(" ".join(f"{clause.title or ''} {clause.text}" for clause in clauses))
    return {
        topic.id: TopicPresence(present=any(keyword in haystack for keyword in topic.keywords))
        for topic in checklist_for(contract_type)
    }


def build_missing_clauses(
    presence: dict[str, TopicPresence],
    contract_type: str | None,
    party: str | None,
) -> list[MissingClause]:
    """Report entries for absent topics, explained from the user's side.

    A topic the analyzer did not report on counts as present (nothing is
    claimed missing without a verdict).
    """
    missing: list[MissingClause] = []
    user = role_label(contract_type, party)
    for topic in checklist_for(contract_type):
        verdict = presence.get(topic.id)
        if verdict is None or verdict.present:
            continue
        importance = topic.importance
        explanation = topic.why
        if party is not None and user:
            if topic.hurts not in (BOTH, party):
                importance = _LOWER[importance]
                explanation = f"Bu eksiklik daha çok karşı tarafı etkiler. {topic.why}"
            else:
                explanation = f"{tr_capitalize(user)} olarak sizin açınızdan önemlidir: {topic.why}"
        missing.append(
            MissingClause(
                topic=topic.id,
                title=topic.title,
                importance=importance,  # type: ignore[arg-type]
                explanation=explanation,
                suggested_clause=topic.suggestion,
                detected_by=verdict.detected_by,
            )
        )
    return missing
