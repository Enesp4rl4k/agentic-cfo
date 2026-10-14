# DEMO_PLAN — "Satın almadan dene" deneyimi

> Hedef: Ziyaretçi kayıt/ödeme olmadan ürünü deneyebilsin; dashboard'lar **anında dolu**,
> akış rehberli, veri açıkça örnek olarak etiketli, ortam güvenli (reset + izolasyon).
> Tarih: 2026-10-14 · `DEVELOPMENT_PLAN.md`'yi tamamlar (Faz A ile paralel).

## 0. Mevcut demo envanteri (sürpriz: Phase 4'te epey bir şey var)

| Varlık | Ne yapıyor | Durum |
|---|---|---|
| `demo/data/logo_tiger_2024.csv` | TechNova 2024 — 163 işlem, ~₺4.8M gelir, 12 ay | ✅ hazır |
| `demo/seed.py` | CSV'yi yükle + analiz başlat (httpx; `--skip-analysis`) | ✅ hazır |
| `POST /demo/seed` | Org'a demo job (idempotent, 24saat) + ARQ pipeline kuyruğu | ✅ hazır |
| `GET /demo/status` | Org'da aktif demo job var mı | ✅ hazır |
| `DELETE /demo/reset` | Docstring'de var, **implementasyonu yok** | ❌ eksik |
| `app/services/demo_seeder.py` | 3 sektör senaryo üretici (SaaS / E-Ticaret / Üretim): sentetik transaction, P&L, e-Fatura, bütçe | ✅ hazır (kullanım düşük) |
| `scripts/seed_demo_org.py` | Demo org seed (tr-TR/TRY) | ✅ hazır |
| `QuickDemoBanner` (upload sayfası) | Tek tık "Örnek Şirket Analizini Başlat" → `/demo/seed` → `/cfo?job_id=` | ⚠️ auth duvarına çarpar |
| `DemoBanner` (layout) | Global şerit, `NEXT_PUBLIC_DEMO_MODE=true` ile | ✅ hazır |
| `IS_DEMO` sampleData (cmo/chro/coo) | Analiz yokken bile örnek kampanya/funnel/SLA/process kartları | ⚠️ 3 sayfada |
| `docker-compose.demo.yml` + `.env.demo` + `README.demo.md` | Tek komutla demo ortamı | ✅ hazır |
| `seed_demo_org` + seeder notu | "demo seeder TRY set eder" | ✅ |

## 1. Boşluklar (ziyaretçi deneyimini kıranlar)

1. **Auth duvarı:** `/demo/seed` → `get_current_user` zorunlu; banner'sız token'ı olmayan
   ziyaretçi 401 alır ve sessizce `/cfo`'ya düşer. **Konuk hesabı yok.**
2. **Anında doluluk yok:** seed gerçek ARQ pipeline'ını kuyruklar (dakikalar; worker + opsiyonel LLM
   gerektirir). Landing'de dashboard'lar BOŞ açılır — ilk izlenim kaybedilir.
3. **Rehberli akış yok:** banner'lar var; sıralı hikâye (yükle→izle→rol rol gez→CTA) yok.
4. **Reset yok:** ortak demo ortamı kirlenir (`/demo/reset` implement edilmemiş).
5. **Public dağıtım hikâyesi yok:** compose var ama ortak domain, rate-limit, otomatik temizlik yok.
6. **Satın alma CTA'sı yok:** demo bitince ne olacağı tanımsız.

## 2. Tasarım kararları (öneri + gerekçe)

| Karar | Öneri | Gerekçe |
|---|---|---|
| Giriş modeli | **Tek tık konuk org** (anonymous user + org + demo data; cookie/token ile geri dönüş) | Paylaşımlı org = kirlik ve gizlilik riski; kayıt duvarı ziyaretçiyi kaçırır. `register`'ın demo varyantı: email'iz `demo+<rand>@…`, parola yok, JWT dön. |
| Anında doluluk | **Deploy/seeding anında ön-hesaplama**: demo org'un company_context + rol sonuçları hazır basılır (pipeline bir kez, kurulumda çalışır); ziyaret anında **hydration yeter** (1.5'in 2sn bound'u ile) | "Canlı" hissi = dolu dashboard; bekleme = izlenim kaybı. Vardiya sırasında pipeline izlemek isteyen için ikinci adım hâlâ `/demo/seed` ile canlı çalıştırılabilir. |
| Etiket | Global `DemoBanner` + örnek-kelime ("TechNova Örnek A.Ş.") + `NEXT_PUBLIC_DEMO_MODE` kalıcı | Dürüstlük kuralı: örnek veri canlı gibi sunulmaz. |
| Rehber | 4 adımlı overlay tour (CFO özeti → anomali → CEO brief → "Sizinkini yükle") — `driver.js` yerine mevcut ui ile basit step-panel | Ürünün "wow" anı = çapraz-ajan hikâyesi; sırayı göstermek gerek. |
| Reset | `DELETE /demo/reset` implement + konuk session bitiminde auto-reset (TTL cron) | Ortak hijyen. |
| CTA | Tour sonu + DemoBanner → "Şirketinizin verisiyle dene" (mail capture) + pricing linki | Dönüşüm. |

## 3. Fazlar

### D1 — Sürtünmesiz giriş (konuk hesabı) — ÖNCELİK 1
- [ ] `POST /demo/guest`: yoksa anonymous user + org (tr-TR/TRY) + JWT; `is_demo` flag.
- [ ] Landing/buton: kayıt olmadan `QuickDemoBanner`-tarzı tek tık → guest token → dolu dashboard.
- [ ] Konuk org `demo` etiketli; `DemoBanner` her zaman görünür (`DEMO_MODE` bağımsız ziyaretçi flag'i).
- [ ] Kapı: test — token'sız `/demo/seed` 401, guest token ile 200; guest org izole (org B → A job'ı 404).

### D2 — Anında dolu dashboard'lar — ÖNCELİK 1
- [ ] **Ön-hesaplama scripti** `scripts/demo_prefill.py`: demo org + `demo_seeder`/Logo Tiger verisi + pipeline'ı bir kez çalıştır → company_context + `last_*_result` snapshot'ları DB'de; ziyaret anında hydration yeter.
- [ ] `IS_DEMO` sampleData kapsamını **6 role** genişlet (cto/ceo/risk/audit için dürüst wire-fixture = normalizer testleriyle aynı veri) — ön-hesaplama bitene kadar degradasyon.
- [ ] Hazırlık durumu: `/demo/status` + landing'de "Örnek analiz hazır" göstergesi; pipeline canlı izleme seçeneği korunur.
- [ ] Kapı: temiz DB → `prefill` → 6 rol sayfası `undefined`/`NaN`/`$` = 0 (Faz A canlı taraması gibi).

### D3 — Rehberli akış (tour) — ÖNCELİK 2
- [ ] 4 adım: (1) CFO özeti & runway, (2) anomali denetimi, (3) CEO brief / çapraz risk, (4) "Şirketinizle deneyin" CTA. Step JSON i18n'de (tr/en).
- [ ] İlk girişte otomatik başlangıç; sidebar'da "Turu tekrarla".
- [ ] auto-chain görünürlüğü (1.6 ile birlikte): demo izleyicisi ajanların çalıştığını görür.

### D4 — Reset + hijyen — ÖNCELİK 2
- [ ] `DELETE /demo/reset` implement (docstring ile hizalı): demo job'ı + context snapshot temizliği.
- [ ] Konuk TTL: X saat sonra org data purge (cron/ARQ task) + rate limit (konuk başına günde N seed).
- [ ] `npm audit` upgrade task'ı gibi: bu iş de yeşil testlerle ayrı sprint'e.

### D5 — Public demo ortamı — ÖNCELİK 3
- [ ] Ayrı deploy (compose tabanlı): `NEXT_PUBLIC_DEMO_MODE=true`, kendi DB volume, seed'li görüntü.
- [ ] Otel: günlük otomatik `prefill` tazeleme, log/metrics, maliyet cap'i (LLM opsiyonel default kapalı).
- [ ] Demo → gerçek geçiş: kayıt olunca gerçek org açılır, demo org bağlanmaz (veri izolasyonu).

### D6 — CTA & ölçüm — ÖNCELİK 3
- [ ] Tour sonu + banner CTA: mail capture + pricing; `POST /demo/lead`.
- [ ] Basit ölçüm: demo başlattı / tur tamamladı / CTA tıkladı sayacları (privacy-hostile değil, sayaç).

## 4. Dürüstlük kırmızı çizgileri (sürer)
- Örnek veri **asla** canlı etiketlenmez: DemoBanner + "Örnek A.Ş." + kaynak notu.
- Ön-hesaplanmış sonuçlar `demo` flag'li gelir; gerçek org verisiyle karışmaz.
- `undefined`/`NaN`/`String(undefined)`/yanlış `$` = 0 (mevcut kapılar demo sayfaları da kapsar).
- Gömülü TR/İ-casing kapısı (`casing-gate.test.ts`) demo bileşenlerini de tarayacak şekilde genişletilecek
  (`components/demo/**` tarama kapsamına eklenir).

## 5. Sıra (öneri)
**D1 → D2 → D4 → D3 → D5 → D6** — önce "gir ve anında gör" (D1+D2 = kritik yol),
güvenlik/hijyen (D4), sonra hikâye (D3), dağıtım (D5), dönüşüm (D6).

D1+D2 bittiğinde: `docker-compose.demo.yml` + `prefill` ile tek komutla **verimsiz bekleme olmadan**
dolu bir demo elde edilir; public URL D5'te gelir.
