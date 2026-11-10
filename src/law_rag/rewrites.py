"""Clause rewrite helpers and deterministic template rewrites.

One rewrite per clause that has at least one finding applying to the user,
covering all of that clause's findings. The LLM writes the suggestion in
batches; the templates below are the offline output and the per-clause
fallback.
"""

from .models import Clause, ClauseRewrite, RiskFinding
from .segmentation import PREAMBLE_ID

# (category, contract type or "*") -> (replacement text, short rationale)
_TEMPLATES: dict[tuple[str, str], tuple[str, str]] = {
    ("cash_payment", "*"): (
        "Ödemeler, alacaklı tarafın sözleşmede belirtilen banka hesabına, açıklama kısmında ilgili dönem yazılarak yapılır; elden ödeme yapılmaz.",
        "Ödemenin banka kanalıyla yapılması ispat sorununu ortadan kaldırır.",
    ),
    ("deposit_forfeiture", "*"): (
        "Kiracı, üç aylık kira bedelini aşmamak üzere güvence bedeli verir. Güvence bedeli, tahliyede tutanakla belgelenen gerçek zararlar mahsup edildikten sonra en geç 30 gün içinde kiracıya iade edilir; tadilat veya başka bir sebeple otomatik olarak irat kaydedilemez.",
        "Güvence bedeli kesintisi gerçek ve belgelenmiş zarara bağlanmalıdır.",
    ),
    ("termination", "lease"): (
        "Taraflar, kira sözleşmesini yalnızca kanunda öngörülen fesih sebepleri ve bildirim sürelerine uyarak yazılı bildirimle sona erdirebilir.",
        "Kiraya verenin tek taraflı ve derhal fesih hakkı kanuni koruma hükümleriyle bağdaşmaz.",
    ),
    ("termination", "employment"): (
        "Taraflar iş sözleşmesini kanundaki bildirim sürelerine uyarak feshedebilir; haklı nedenle derhal fesih ancak kanunda sayılan hâllerde mümkündür ve fesih sebebi yazılı bildirilir.",
        "Fesih hakkı kanuni bildirim süreleri ve haklı neden şartına bağlanmalıdır.",
    ),
    ("termination", "*"): (
        "Taraflardan her biri en az 30 gün önceden yazılı bildirimde bulunarak sözleşmeyi feshedebilir. Haklı nedenle fesihte, aykırılık yazılı olarak bildirilir ve giderilmesi için en az 15 günlük süre verilir.",
        "Fesih hakkı karşılıklı, bildirim süreli ve düzeltme imkânı tanıyan şekilde dengelenmelidir.",
    ),
    ("penalty_clause", "lease"): (
        "Kiranın geç ödenmesi hâlinde yalnızca kanuni temerrüt sonuçları uygulanır; kiracıya ceza koşulu veya sonraki kira bedellerinin muaccel olacağına ilişkin bir yükümlülük getirilmez.",
        "Konut ve çatılı işyeri kiralarında geç ödemeye bağlı ceza koşulu ve muacceliyet kaydı geçersizdir.",
    ),
    ("penalty_clause", "*"): (
        "Sözleşmeye aykırılık hâlinde ödenecek ceza, aykırılığın ağırlığıyla orantılı olarak ... TL'yi ve sözleşme bedelinin %10'unu aşamaz; ceza ancak yazılı ihtara rağmen aykırılık 15 gün içinde giderilmezse istenebilir.",
        "Cezai şart üst sınıra ve ihtar şartına bağlanarak orantılı hâle getirilmelidir.",
    ),
    ("unlawful_entry", "*"): (
        "Kiraya veren, bakım, satış veya yeniden kiralama için zorunlu olduğu ölçüde ve en az 48 saat önceden bildirimde bulunarak, kiracının uygun bulduğu makul saatlerde kiralananı gezip görebilir; kiracının izni olmadan kiralanana girilemez.",
        "Kiralanana giriş, kiracının önceden bilgilendirilmesine ve rızasına bağlanmalıdır.",
    ),
    ("eviction_undertaking", "*"): (
        "Bu sözleşme kapsamında kiracıdan tahliye taahhüdü alınmaz; taraflar tahliye konusunda ancak kiralananın tesliminden sonra ayrı ve tarihli bir belgeyle anlaşabilir.",
        "Teslimden önce alınan tahliye taahhüdüne dayanılamaz.",
    ),
    ("rent_increase", "*"): (
        "Yenilenen kira dönemlerinde kira bedeli, bir önceki kira yılında tüketici fiyat endeksindeki on iki aylık ortalamalara göre değişim oranını geçmemek üzere artırılır.",
        "Artış oranı yasal ölçüyle sınırlandırılmalıdır.",
    ),
    ("jurisdiction", "*"): (
        "Bu sözleşmeden doğan uyuşmazlıklarda, kanunun zorunlu yetki kuralları saklı kalmak üzere, taşınmazın veya davalının yerleşim yerinin bulunduğu yer mahkemeleri ve icra daireleri yetkilidir.",
        "Yetki şartı zorunlu yetki kurallarıyla uyumlu ve taraflar için erişilebilir olmalıdır.",
    ),
    ("data_protection", "*"): (
        "Taraflar, sözleşme kapsamında işlenen kişisel veriler bakımından 6698 sayılı Kanun'a uygun hareket eder; veri işleyen sıfatıyla hareket eden taraf verileri yalnızca diğer tarafın talimatıyla işler, gerekli güvenlik tedbirlerini alır ve ihlali en geç 24 saat içinde bildirir.",
        "Veri işleme rolleri ve güvenlik yükümlülükleri açıkça paylaştırılmalıdır.",
    ),
    ("intellectual_property", "*"): (
        "Sözleşme kapsamında üretilen eserler üzerindeki çoğaltma, yayma, işleme, temsil ve umuma iletim hakları, ilgili bedelin ödenmesiyle birlikte süre ve yer sınırı olmaksızın karşı tarafa devredilir; önceden var olan araçlar için kullanım lisansı verilir.",
        "Mali hakların yazılı ve ayrı ayrı gösterilerek devri belirlilik sağlar.",
    ),
    ("force_majeure", "*"): (
        "Doğal afet, salgın, savaş, siber saldırı ve resmi makam kararları gibi tarafların kontrolü dışındaki olaylar mücbir sebep sayılır; etkilenen taraf durumu 7 gün içinde bildirir ve mücbir sebep 60 günü aşarsa taraflardan her biri sözleşmeyi tazminatsız feshedebilir.",
        "Mücbir sebebin tanımı, bildirim süresi ve sonuçları netleştirilmelidir.",
    ),
    ("payment_interest", "*"): (
        "Ödemenin gecikmesi hâlinde, yazılı ihtardan itibaren yalnızca kanuni temerrüt faizi uygulanır.",
        "Gecikme faizi kanuni sınırlarla uyumlu ve öngörülebilir olmalıdır.",
    ),
    ("liability", "*"): (
        "Tarafların sözleşmeden doğan toplam sorumluluğu son 12 ayda ödenen bedelle sınırlıdır; bu sınır kast, ağır kusur, kişisel veri ihlali ve fikri mülkiyet ihlallerinden doğan zararlara uygulanmaz.",
        "Ağır kusurdan sorumsuzluk kaydı geçersizdir; sorumluluk sınırı karşılıklı ve istisnalı olmalıdır.",
    ),
    ("dispute_resolution", "*"): (
        "Taraflar uyuşmazlıkları önce iyi niyetli müzakereyle çözmeye çalışır; 30 gün içinde çözülemeyen uyuşmazlıklarda, arabuluculuğa ilişkin zorunlu hükümler saklı kalmak üzere, sözleşmede açıkça gösterilen mahkemeler veya tahkim kurumu yetkilidir.",
        "Uyuşmazlık çözüm yolu açık, yazılı ve tarafların erişebileceği şekilde belirlenmelidir.",
    ),
    ("probation_period", "*"): (
        "İş sözleşmesinde iki aylık deneme süresi öngörülmüştür; bu süre içinde taraflar sözleşmeyi bildirim süresine gerek olmaksızın ve tazminatsız feshedebilir.",
        "Deneme süresi kanundaki iki aylık sınırla uyumlu olmalıdır.",
    ),
    ("non_compete", "*"): (
        "İşçi, sözleşmenin sona ermesinden itibaren bir yıl süreyle, yalnızca ... ilinde ve işverenin fiilen faaliyet gösterdiği alanda rakip bir işletmede çalışmamayı yazılı olarak üstlenir.",
        "Rekabet yasağı süre, yer ve iş türü bakımından sınırlı olmalıdır.",
    ),
}
_GENERIC = (
    "Bu madde, tarafların hak ve yükümlülükleri dengeli, açık ve ölçülebilir olacak şekilde yeniden düzenlenmelidir.",
    "Madde hukuki inceleme sonucunda dengelenmelidir.",
)


def template_for(category: str, contract_type: str | None) -> tuple[str, str]:
    return _TEMPLATES.get((category, contract_type or "*")) or _TEMPLATES.get((category, "*")) or _GENERIC


def clauses_to_rewrite(
    clauses: list[Clause],
    findings: list[RiskFinding],
) -> list[tuple[Clause, list[RiskFinding]]]:
    """Clauses (in contract order) with their applicable findings."""
    by_clause: dict[str, list[RiskFinding]] = {}
    for finding in findings:
        if finding.applies_to_user and finding.clause_id and finding.clause_id != PREAMBLE_ID:
            by_clause.setdefault(finding.clause_id, []).append(finding)
    return [(clause, by_clause[clause.id]) for clause in clauses if clause.id in by_clause]


def template_rewrite(clause: Clause, findings: list[RiskFinding], contract_type: str | None) -> ClauseRewrite:
    texts: list[str] = []
    reasons: list[str] = []
    for finding in findings:
        text, reason = template_for(finding.category, contract_type)
        if text not in texts:
            texts.append(text)
        if reason not in reasons:
            reasons.append(reason)
    return ClauseRewrite(
        clause_id=clause.id,
        finding_ids=[finding.id for finding in findings],
        original_text=clause.text,
        suggested_text=" ".join(texts),
        rationale=" ".join(reasons[:2]),
        generated_by="rule_based",
    )
