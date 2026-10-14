# Mimari Kararlar

## D1 — Arayüzü FastAPI aynı porttan sunar

**Bağlam:** Arayüz ile API ayrı portlarda olursa CORS ayarı ve iki süreç gerekir; kullanıcı
bugün zaten iki terminal yönetiyor (backend + Yargı MCP).
**Karar:** `npm run build` çıktısı (`frontend/dist`) varsa FastAPI onu `/` altında sunar;
geliştirmede Vite proxy'si kullanılır.
**Yenilen seçenek:** Ayrı Vite/nginx sunucusu + CORS.
**Kabul edilen sonuç:** Arayüz değişince `npm run build` tekrar çalıştırılmalı; unutulursa
eski arayüz görünür.
**Yeniden düşün:** Arayüz backend'den bağımsız dağıtılacaksa (ör. CDN) ya da birden fazla
backend'e bağlanacaksa.

## D2 — Senkron istek + istemci tarafı bekleme ekranı, iş kuyruğu yok

**Bağlam:** Analiz 50–120 sn sürüyor. Gerçek ilerleme için ya iş/polling API'si ya da akış
(SSE) gerekir; ikisi de backend'de yeni durum ve uç nokta demek.
**Karar:** Mevcut senkron uç nokta kullanılır; arayüz geçen süreyi, beklenen aralığı ve
backend'in sırayla yaptığı işleri (ilerleme iddiası olmadan) gösterir, iptal sunar.
**Yenilen seçenek:** `POST /jobs` + `GET /jobs/{id}` ya da SSE ile aşama bildirimi.
**Kabul edilen sonuç:** Kullanıcı hangi aşamada olunduğunu bilmez; sekme kapanırsa analiz kaybolur.
**Yeniden düşün:** Analiz düzenli olarak 180 sn'yi aşarsa, birden fazla eşzamanlı kullanıcı
olursa ya da bir proxy/ters vekil 60 sn'de isteği kesiyorsa.

## D3 — Kimlik doğrulama yok, yalnız 127.0.0.1

**Bağlam:** Tek kullanıcı, yerel makine.
**Karar:** Arayüz ve API yalnız `127.0.0.1`'de; oturum açma yok.
**Kabul edilen sonuç:** Makineye erişen herkes kullanabilir.
**Yeniden düşün:** Uygulama ağa açılacaksa ya da ikinci bir kullanıcı olacaksa — o gün
kimlik doğrulama ve istek sınırlama aynı değişiklikte gelir.

## D4 — Bileşen/durum kütüphanesi yok; düz CSS

**Bağlam:** Tek sayfa, tek rapor, ~6 bileşen.
**Karar:** React'in kendi `useState`'i ve düz CSS (CSS değişkenleri).
**Yenilen seçenek:** MUI/Chakra, Tailwind, Redux/Zustand, React Router.
**Kabul edilen sonuç:** Erişilebilir etkileşimler (odak, klavye) elle yazılır.
**Yeniden düşün:** İkinci bir sayfa (ör. rapor geçmişi) ya da 15+ bileşen olursa router ve
bileşen kütüphanesi değerlendirilir.
