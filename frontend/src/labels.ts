import type { Severity } from "./types";

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Kritik",
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
};

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

const CATEGORY_LABEL: Record<string, string> = {
  cash_payment: "Elden ödeme",
  deposit_forfeiture: "Depozito",
  termination: "Fesih",
  penalty_clause: "Cezai şart",
  unlawful_entry: "Konuta izinsiz giriş",
  eviction_undertaking: "Tahliye taahhüdü",
  rent_increase: "Kira artışı",
  jurisdiction: "Yetkili mahkeme",
  data_protection: "Kişisel veriler",
  intellectual_property: "Fikri mülkiyet",
  force_majeure: "Mücbir sebep",
  payment_interest: "Gecikme faizi",
  liability: "Sorumluluk",
  dispute_resolution: "Uyuşmazlık çözümü",
  general_risk: "Genel risk",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? category.replaceAll("_", " ");
}

// The backend reports limitations in English; known ones are shown in Turkish.
const LIMITATION_RULES: [RegExp, (match: RegExpMatchArray) => string][] = [
  [/^Precedent search covered only the (\d+) most severe of (\d+) findings\.$/, (m) =>
    `Emsal karar yalnız en ciddi ${m[1]} risk için arandı (toplam ${m[2]}).`],
  [/^(.+) was unavailable for some calls; (.+) was used instead\.$/, (m) =>
    `${m[1]} bazı adımlarda yanıt vermedi; yerine ${m[2]} kullanıldı.`],
  [/^No sufficiently relevant Yargi MCP decision was found for some findings\.$/, () =>
    "Bazı riskler için yeterince ilgili emsal karar bulunamadı."],
  [/^Some Yargi MCP results had no excerpt and were deprioritized\.$/, () =>
    "Metni alınamayan bazı kararlar geri plana alındı."],
  [/^Yargi MCP rate limit was hit; some searches were skipped\.$/, () =>
    "Karar arama servisinin hız sınırına takılındı; bazı aramalar atlandı."],
  [/^Yargi MCP searches exceeded the total time limit; partial results are shown\.$/, () =>
    "Karar araması süre sınırını aştı; bulunanlar gösteriliyor."],
  [/^Some Yargi MCP searches failed\.$/, () => "Bazı karar aramaları başarısız oldu."],
  [/^Gemini risk analysis failed for some clauses; rule-based analysis was used instead\.$/, () =>
    "Yapay zekâ bazı maddeleri değerlendiremedi; bu maddelerde kural tabanlı inceleme kullanıldı."],
  [/^Gemini summary failed; a rule-based excerpt is shown instead\.$/, () =>
    "Yapay zekâ özet üretemedi; sözleşmenin başından bir alıntı gösteriliyor."],
  [/^Gemini clause segmentation failed; line-based segmentation was used\.$/, () =>
    "Maddelere ayırma yapay zekâyla yapılamadı; metin satır satır bölündü."],
  [/^Gemini query generation failed for some findings; template queries were used\.$/, () =>
    "Bazı riskler için arama sorgusu hazır şablondan üretildi."],
  [/^Contract is longer than the summary limit; the summary covers only the beginning\.$/, () =>
    "Sözleşme uzun olduğu için özet yalnız baş kısmı kapsıyor."],
  [/^Only the (\d+) most severe findings are reported\.$/, (m) =>
    `Yalnız en ciddi ${m[1]} risk raporlandı.`],
  [/^No risk findings were detected by the MVP rules\.$/, () => "Hiç risk tespit edilmedi."],
];

export function limitationLabel(text: string): string {
  for (const [pattern, render] of LIMITATION_RULES) {
    const match = text.match(pattern);
    if (match) return render(match);
  }
  return text;
}
