# Sözleşme Analiz Arayüzü — Sistem Mimarisi

**Durum:** Taslak
**Tarih:** 2026-10-14
**Yazar:** Maksut Akgün

## 1. Ne yapıyoruz ve neden

Backend bugün bir sözleşmeyi analiz edip JSON döndürüyor: maddeler, riskler, emsal kararlar,
sınırlamalar. Bu JSON'u ancak Swagger'dan dosya yükleyip okuyan biri görebiliyor; "sistem işe
yarıyor mu" sorusuna cevap vermek için ham JSON'u satır satır yorumlamak gerekiyor.

Arayüz, bir kullanıcının (hukukçu veya ürünü değerlendiren kişi) sözleşmeyi sürükleyip
bırakarak yüklemesini ve sonucu **kanıt zinciriyle** görmesini sağlar: risk → ilgili madde metni →
o riske bağlanan emsal karar → kararın gerekçe alıntısı. Ayrıca analizi gerçekten hangi
motorların yaptığı (Gemini mi kural tabanlı mı, gerçek Yargı MCP mi sahte mi) ve neyin eksik
kaldığı (`limitations`) açıkça gösterilir.

**Başarı ölçütü:** `samples/` altındaki iki sözleşmeden biri yüklendiğinde, kullanıcı JSON'a
hiç bakmadan her riskin hangi maddeden çıktığını ve hangi karara dayandığını tek ekranda görür.

## 2. Kısıtlar ve varsayımlar

| # | Kısıt | Kaynak | Tasarıma etkisi |
|---|-------|--------|-----------------|
| C1 | Tek kullanıcı, yerel Windows makinesi | Kullanıcı | Sunucu, kimlik doğrulama, dağıtım yok |
| C2 | Analiz 50–120 sn sürüyor, senkron tek istek | Mevcut backend | Bekleme deneyimi tasarımın merkezi (§4) |
| C3 | Backend `127.0.0.1`'e bağlı, kimlik doğrulama yok | Mevcut backend | Arayüz de yalnız yerelde sunulur |
| C4 | Ekip Python biliyor, Node 26 kurulu | Ortam | Vite + React + TypeScript; ek çerçeve yok |
| C5 | Sözleşme metni kişisel veri içerebilir | Alan (KVKK) | Tarayıcıda kalıcı saklama yok (§8) |

| # | Varsayım | Yanlışsa | Güven |
|---|----------|----------|-------|
| A1 | Tarayıcı ve Vite proxy'si 120 sn'lik tek isteği kesmeden bekler | Dev modda istek yarıda kalır; proxy timeout'u açıkça ayarlanır ya da iş/polling API'sine geçilir (D2) | Orta |
| A2 | FastAPI, derlenmiş arayüzü aynı porttan statik olarak sunabilir | İki süreç ve CORS gerekir | Yüksek |
| A3 | Kullanıcı aşama aşama gerçek ilerleme değil, geçen süreyi ve beklenen süreyi görmekle yetinir | Akış (SSE) ile gerçek aşama bildirimi gerekir (D2) | Orta |

## 3. Boyutlandırma

| Büyüklük | Tahmin | Nasıl |
|----------|--------|-------|
| Kullanıcı | 1 | C1 |
| Analiz / gün | ~10 | Değerlendirme/deneme kullanımı; her biri 50–120 sn ⇒ en fazla ~20 dk iş/gün |
| Eşzamanlı analiz | 1 | Tek kullanıcı; Yargı hız sınırı zaten eşzamanlılığı 1'de tutuyor |
| Yanıt boyutu | ~20–60 KB JSON | ≤10 madde × ~300 B + ≤10 bulgu × ~500 B + ≤5 karar × 1200 B alıntı + başlıklar |
| Arayüz paket boyutu | ~150 KB gzip | React + ReactDOM ~45 KB gzip + uygulama kodu |
| p95 süre | 120 sn analiz; arayüz etkileşimi < 100 ms | Analiz süresini backend belirler |

**Sayıların söylediği:** Bu bir sunucu sistemi değil, tek sayfalık bir istemci. Veritabanı,
önbellek, kuyruk, durum yönetim kütüphanesi, UI bileşen kütüphanesi gerektirecek hiçbir sayı yok.

## 4. Zor kısım

İki şey zor; ikisi de kullanıcının listesinde açıkça yoktu:

1. **İki dakikalık bekleme.** Senkron bir istekte 2 dakika boş ekran, kullanıcının sistemi
   bozuk sanmasına yol açar. Tasarım: istek boyunca geçen süre sayacı, beklenen süre aralığı ve
   backend'in sırayla yaptığı işlerin listesi gösterilir. Liste *gerçek ilerleme değildir* ve
   öyle sunulmaz; gerçek aşama bilgisi gerekirse D2'deki koşul geçerlidir. İstek iptal edilebilir.
2. **Güven.** Hukuki bir çıktıda "işe yarıyor" hissi, her iddianın kaynağının görünmesinden
   gelir. Tasarım: bulgu kartı tıklanınca bağlı madde metni ve bağlı karar(lar) aynı görünümde
   açılır; motor bilgisi ve sınırlamalar özetin üstünde, gizlenmeden durur. Gemini'nin madde
   numarası uydurabildiği (README'de not edildi) için her karar ve bulgu "hukukçu kontrolü
   gerekir" uyarısıyla gösterilir.

## 5. Veri modeli

Kalıcı veri yok; `schema.sql` bu yüzden yazılmadı. Tek veri yapısı backend'in döndürdüğü
`ContractReport`'tur; arayüzdeki TypeScript tipleri `src/law_rag/models.py`'nin birebir
yansımasıdır (`frontend/src/types.ts`).

| # | Değişmez kural | Ne sağlıyor |
|---|----------------|-------------|
| I1 | Arayüz tipleri backend modeliyle aynı alanları taşır | Fixture testi: gerçek bir API yanıtı (`frontend/src/fixtures/report.json`) tiplere uyar ve render edilir |
| I2 | Bir bulgunun `clause_id`'si yoksa ya da madde bulunamazsa arayüz çökmez | Bileşen kodu; fixture testinde `clause_id: null` örneği |

**Silme ve saklama:** Rapor yalnız bellekte tutulur; sayfa yenilenince kaybolur. Bilinçli (C5).

**Sonradan değiştirmesi pahalı:** `ContractReport` alan adları. Backend'de bir alan adı
değişirse arayüz kırılır; I1 testi bunu yakalar.

## 6. Sistem tasarımı

| Bileşen | Sorumluluk | Teknoloji | Neden var |
|---------|------------|-----------|-----------|
| Arayüz | Yükleme, bekleme, rapor görünümü | Vite + React 19 + TypeScript, düz CSS | §1 |
| Mevcut FastAPI | Analiz; üretimde `frontend/dist`'i `/` altında sunar | Değişmiyor, yalnız statik sunum eklenir | A2: tek URL, CORS yok |
| Vite dev sunucusu | Geliştirmede sıcak yenileme; `/api`'yi FastAPI'ye yönlendirir | Vite proxy | Yalnız geliştirme |

```
Tarayıcı ──► http://127.0.0.1:<APP_PORT>/          (derlenmiş arayüz, FastAPI StaticFiles)
         └─► http://127.0.0.1:<APP_PORT>/api/v1/... (aynı süreç, aynı köken)
                         │
                         ├─► Gemini API
                         └─► Yargı MCP (127.0.0.1:8001)
```

**Ana akış — analiz:** Kullanıcı dosyayı bırakır → arayüz uzantı ve boyutu (10 MB) yerelde
kontrol eder → `multipart/form-data` ile `POST /api/v1/contracts/analyze` → bekleme ekranı
(sayaç + iptal) → 200 ise rapor görünümü; 400/413/422/500 ise backend'in `detail.code`
ve `detail.message` alanlarıyla hata kartı ve "tekrar dene".

**Bilinçli olarak yok:** durum yönetimi kütüphanesi, router, UI kütüphanesi, Tailwind,
rapor geçmişi, PDF dışa aktarma, kimlik doğrulama. Geri gelme koşulları `DECISIONS.md`'de.

## 7. Sözleşmeler

Arayüzün kullandığı tek uç nokta mevcut olandır; yeni uç nokta eklenmez.

- `POST /api/v1/contracts/analyze` — form alanları `file` (zorunlu, .pdf/.docx) ve
  `contract_type` (isteğe bağlı: `service` | `lease`). Yanıt: `ContractReport` (README).
- Hata gövdesi: `{"detail": {"code": string, "message": string}}`; 422 için FastAPI'nin
  standart `detail` listesi. Arayüz ikisini de okunur metne çevirir.
- Yeniden deneme: analiz yan etkisiz (yazma yok), aynı dosyayla tekrar göndermek güvenli.

## 8. Güvenlik ve erişim

- Kimlik doğrulama yok; tek savunma `127.0.0.1` bağlaması (C3). Ağa açılması D3'teki koşula bağlı.
- Sözleşme metni ve rapor `localStorage`/`sessionStorage`'a yazılmaz, URL'ye konmaz (C5).
- Karar alıntıları ve sözleşme metni düz metin olarak render edilir; `dangerouslySetInnerHTML`
  kullanılmaz (dış kaynaktan gelen metin).
- Gemini API anahtarı yalnız backend `.env`'inde kalır; arayüze hiç ulaşmaz.

## 9. Operasyon

### 9.1 Çalıştırma
Üretim (kullanıcının yolu): `cd frontend && npm install && npm run build`, sonra mevcut
`uv run python main.py`; arayüz `http://localhost:<APP_PORT>/`. Geliştirme: ek olarak
`npm run dev` (Vite, `/api` proxy'si `API_TARGET`'a, varsayılan `http://127.0.0.1:8000`).
Geri alma: `frontend/dist` silinirse FastAPI eskisi gibi yalnız API sunar.

### 9.2 Gözlemlenebilirlik
Tek kullanıcılı yerel araç: izleme yok. Görünürlük raporun kendisinde: `llm_engine`,
`yargi_source`, `limitations` her zaman ekranda.

### 9.3 Arıza durumları

| Arıza | Kullanıcının gördüğü | Nasıl fark edilir | Tepki |
|-------|---------------------|-------------------|-------|
| Backend kapalı | "Sunucuya ulaşılamadı" kartı | `fetch` ağ hatası | Kartta başlatma komutu |
| Yargı MCP kapalı | Karar yok + sınırlama notu | `limitations` ve kararsız rapor | Rapordaki uyarı rozeti |
| Gemini erişilemez | `llm_engine` "rules" veya yedek model notu | `llm_engine` / `limitations` | Motor rozeti sarı/kırmızı |
| Analiz 3 dk'yı aşar | Sayaç uyarısı, iptal düğmesi | İstemci tarafı süre (180 sn) | İptal / tekrar dene |
| Desteklenmeyen/büyük dosya | Yükleme öncesi uyarı | İstemci kontrolü + 400/413 | Doğru dosyayı seç |
| `frontend/dist` eski kalır | Yeni alanlar görünmez | Derleme sonrası değişiklik yok | `npm run build` |

### 9.4 Yedekleme
Kalıcı veri yok; yedeklenecek bir şey yok.

### 9.5 Maliyet
Arayüzün ek maliyeti 0. Analiz maliyeti backend'e ait (Gemini ücretsiz katman; ücretli
katmana geçiş KVKK kararına bağlı, README).

## 10. Doğrulama

| İddia | Ne doğruluyor | Ne zaman |
|-------|---------------|----------|
| Tipler backend yanıtıyla uyumlu (I1) | Gerçek API yanıtından alınmış fixture ile render testi | `npm test` |
| Eksik madde/karar çökertmez (I2) | Aynı testte `clause_id: null`, boş karar listesi | `npm test` |
| Hata gövdesi okunur gösterilir | API istemcisi birim testi (400, 422, ağ hatası) | `npm test` |
| FastAPI arayüzü ve API'yi aynı porttan sunar (A2) | `TestClient` testi: `/` HTML, `/api/...` JSON | `pytest` |
| 120 sn'lik istek tamamlanır (A1) | Elle: örnek sözleşmeyi derlenmiş arayüzden analiz et | M0 ve M2 sonunda |

## 11. Yol haritası

### Milestone 0 — riski öldür
- **A2 + A1:** FastAPI'ye statik sunumu ekle, en küçük bir HTML sayfasından gerçek analiz
  isteği at. Geçme ölçütü: aynı porttan 200 ve ~1–2 dk sonra rapor JSON'u. Başarısızsa: iki
  süreç + CORS ya da iş/polling API'si.

### Milestone'lar
| Milestone | Bittiğinde gösterilebilir olan |
|-----------|-------------------------------|
| M1 | Dosya yükle → bekleme ekranı → rapor özeti, motor rozetleri, sınırlamalar |
| M2 | Bulgu ↔ madde ↔ karar kanıt zinciri; örnek sözleşmeyle uçtan uca çalışıyor |
| M3 | Testler (`npm test`, `pytest`) yeşil; README'de tek komutluk kullanım |

### Kapsam dışı
Kimlik doğrulama, çoklu kullanıcı, rapor geçmişi/veritabanı, PDF/Word dışa aktarma, gerçek
zamanlı aşama ilerlemesi, mobil öncelikli tasarım. Hepsi tek kullanıcılı bir değerlendirme
aracı için gereksiz; geri gelme koşulları `DECISIONS.md`'de.

## 12. Açık sorular
- KVKK: sözleşmelerin Gemini ücretsiz katmanına gönderilmesi uygun mu? (Kullanıcı; gerçek
  sözleşme yüklenmeden önce.)
