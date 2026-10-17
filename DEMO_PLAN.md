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
| `IS_DEMO` sampleData | cmo/chro/coo örnek CSV + cto "Örnek veriyle doldur" + risk/ceo rozetli wire-fixture | ✅ tüm roller (audit'in "Örnek veri yükle"si ürün özelliği) |
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

### D1 — Sürtünmesiz giriş (konuk hesabı) — ÖNCELİK 1 ✅ (2026-10-14)
- [x] `POST /demo/guest`: anonymous user + org (tr-TR/TRY) + JWT, `/auth/login` ile aynı token şekli (NextAuth SSO kısa yolu). `is_demo` kolonu yok → migration'sız etiketleme: org `demo-` slug öneki + açıklama; gate = `settings.demo_mode` → 403 (güvenli varsayılan: kapalı).
- [x] Landing/buton: Hero + CTABand "Demoyu Dene" ve login "Kayıt olmadan demoyu dene" → `startGuestDemo()` → konuk oturum → `/upload` (QuickDemoBanner ateşleyici). "Dolu dashboard" iddiası D2 prefill'e bağlı — şimdilik tek tık → tek tık örnek analiz.
- [x] Konuk org `demo` etiketli ✓; `DemoBanner` her zaman görünür → `NEXT_PUBLIC_DEMO_MODE` env bayrağı (D5).
- [x] QuickDemoBanner token düzeltmesi: `useSession()` fallback'i — prop'suz çağrída seed 401 → sessizce boş dashboard'a atlıyordu.
- [x] Kapı: backend 6 test (`test_demo_guest.py`: token'sız `/demo/seed` 401, guest 200; izolasyon — org B A'nın job'ını görmez; demo_mode-off 403; org tr-TR/TRY) + frontend 4 test (`demo-guest.test.tsx`: başarılı akış, dürüst hata durumu, tokensız yanıt, csrf-race false-success gate).
- [x] **İki intermittent bounce giderildi (2026-10-14, ×15 + ×10 canlı loop)**: (1) hydration öncesi ölü click → buton mounted'a kadar `disabled`; (2) csrf cookie yarışı (geç düşen duplicate `/api/auth/session` Set-Cookie'si csrf token'ını eziyor → callback 200 + error'süz URL + sessionsız) → `startGuestDemo` oturumu `getSession()` ile doğrular + seyrek yarışı **tek otomatik yeniden denemeyle** aşar (canlı: yarış durumunda bile sonuç `/upload`), middleware `pages: {signIn, error}` = `/auth/login` ile doğrudan kendi login'ine yönlendirir (ekstra `/api/auth/signin` hop + mutlak callbackUrl yok).

### D2 — Anında dolu dashboard'lar — ÖNCELİK 1 (2026-10-14: canlı kapı geçti, kalan: degradasyon + landing göstergesi)
- [x] **Ön-hesaplama scripti** `backend/scripts/demo_prefill.py`: golden org (`slug=demo-golden`) + Logo Tiger CSV + CFO pipeline (`run_cfo_analysis` inline, Redis/ARQ gerekmez) + C-suite (cto/cmo/coo/chro/risk/audit, frontend örnek CSV'leriyle) + CEO synthesis; review-gate tutarsa ayakta onay (`approve` aynası + `devam_et`). Idempotent (eksik parçaları tamamlar, `--force` yeniler). Yerel doğrulama: **8/8 `last_*_result` dolu** (~3sn/ajan, LLM placeholder → şablon anlatım normal).
- [x] **Klonlama** `backend/app/services/demo_template.py`: `/demo/guest` artık golden'dan AnalysisJob + Report + Transaction + Anomaly + CompanyContext + semantic snapshot kopyalar; job id yeniden üretilir, JSON'daki eski job/org id referansları patch'lenir → her konuk kendi satırlarına sahip (izolasyon korunur), `/dashboard/{job}` sahiplik + `/context/me` aynı anda çalışır. Golden yoksa sessiz no-op (D1 davranışı).
- [x] **Demo CSV yolu düzeltmesi**: `api/demo.py` `parents[4]` repoya değil reporun üstüne bakıyordu → bundled `logo_tiger_2024.csv` hiç bulunamıyor, her seed sessizce 25 satırlık fallback'e düşüyordu → `parents[3]`.
- [x] `/demo/status`: klonlu konukta `has_demo=True` (QuickDemoBanner hazır göstergesi ✓).
- [x] Kapı: `tests/test_demo_clone.py` 7 test (boş-org davranışı, klon doluluğu + org_id patch, dashboard sahiplik+payload patch, iki konuk izolasyonu 404, status, idempotent, Redis'siz context okuma) + `PUBLIC_ROUTES`'a `POST /demo/guest` eklendi (`test_route_access` kapısı).
- [x] **COO normalizer öz-şekil düzeltmesi**: `coo-result.ts` `processes`/`sla` yalnızca satır dizisi kabul ediyordu → `context.last_coo_result` ÖZET şekli geldiğinde (`by_process` + `toc_analysis` + `sla_breach_rate`) `null` → sayfa sonsuza dek boş form gösteriyordu. Artık özet kabul + türetme (TOC sıralı satırlar, `impact_score ← throughput_loss_pct`, TOC'de olmayan satırda tavsiye/etki uydurulmaz). Gate: `coo-normalizer.test.ts` aggregate fixture (9 test).
- [x] **Ölü click düzeltmesi (GuestDemoButton)**: hydration öncesi click handler'a hiç ulaşmıyordu (dev sunucu CPU yarışında 3/10 gözlemlendi) → buton server HTML'de `disabled`, mounted olunca aktifleşir (Playwright `click()` enable'ı bekler; gerçek ziyaretçi de ölü tıklama görmez).
- [x] **Tarama aracı**: `scripts/scan_demo_pages.py` — gerçek tarayıcıda D1→D2 akışı (Demoyu Dene → seed → sayfalar), dürüstlük desenleri (`undefined`/`NaN`/`$`/`null`/`[object Object]`) + auth-bounce denetimi, ekran görüntüsü kanıtı.
- [x] Kapı: canlı 6 rol sayfası `undefined`/`NaN`/`$` = 0 taraması → **10/10 sayfa temiz** (command-center, cfo, ceo, cto, cmo, coo, chro, risk, audit, pnl); cfo/cmo/coo/chro/ceo/cto context'ten dolu (CFO 163 işlem ₺ KPI'lar, CHRO KPI+risk+anlatım, COO ToC kartları); risk/audit sayfaları context okumuyor → dürüst "Analizi çalıştır" boş durumu (6 rolün dışında).
- [x] **Hidrasyon `cancelled` yarışı kapatıldı (5 rol sayfası)**: context effect'i `orgId` flip'inde (undefined → org) yeniden çalışırken önceki başarılı yanıtı `cancelled` ile düşürüyordu → sonraki fetch sessiz başarısız olursa sayfa sonsuza dek boş form (canlı taramada /cmo 3 kez 1058 karakter). Artık aynı-veri hydrasyonu rerun'da **iptal edilmiyor** (geç gelen başarılı yanıt da landırılır; React18 unmount setState no-op); CEO'da dönem duyarlı brief/history kısmı `cancelled` korunarak ayrı effect'e bölündü.
- [x] `IS_DEMO` sampleData **6 role** tamam (2026-10-14): cmo/coo/chro örnek CSV + audit "Örnek veri yükle" (ürün özelliği) + cto fill butonu zaten vardı; kalan **risk + ceo wire-fixture** `lib/demo-samples.ts`'e eklendi (`SAMPLE_RISK_WIRE`/`SAMPLE_CEO_WIRE`). Örnek veri yalnız `NEXT_PUBLIC_DEMO_MODE=true` **ve** canlı sonuç yokken gösterilir, sayfa her zaman "**Örnek veri**" rozeti taşır (`t.csvInput.sampleData`), gerçek sonuç/brief gelince örnek tamamen düşer. Fixture'lar aynı normalizer'dan geçer (`normalizeRiskCascadeReport`/`normalizeCEOResult`) — önceden kurulmuş view yok, key değişirse kapı kırılır. Kapı: `demo-samples.test.tsx` 6 test (2 wire-fidelity: threshold-tutarlı counts + `undefined`/`NaN` yok; 4 honesty: bayraklı örnek, bayraksız dürüst boş durum, canlı "Analizi Çalıştır" erişilebilir). Canlı: scan 10/10 temiz; /risk 624→1091 karakter + rozetli örnek KPI'lar (Yükselmiş 6/10, 1 kırmızı, 2 amber); /ceo live'da "Güncel şirket bağlamı" rozeti, örnek görünmez.
- [ ] Landing "Örnek analiz hazır" göstergesi (D3 tour ile birlikte).
- [x] **CTO golden girdileri** (2026-10-14): `demo_prefill.py` `_CTO_INPUTS` (faturalı-bulut/sprint CSV + git `--stat` log + incident CSV + sprint CSV — 13 commit'lik hotspot'ler, tek-yazar bus-factor, SLA ihlalleri) + frontend `SAMPLE_CTO_INPUTS` ile tek "**Örnek veriyle doldur**" butonu (`IS_DEMO`, tr/en `fillWithSample`). İki literal **byte-for-byte ayna** `test_demo_prefill_cto_inputs.py` ile kilitli (parser sinyalleri + ayna = 2 test). Canlı: konuk CTO **3.5/10 "Takip edilmeli"** dolu vitrin; reset → buton → 4 alan da dolu (fill check PASS, 594/4152/807/270 chars).
- [x] **Golden context lost-update hardening** (2026-10-14): `company_context_snapshots` tüm-satır read-modify-write → eşzamanlı yazar (zincir başındaki kopyayı geç kaydeden) başka ajanın sonucunu geri alabiliyordu (gözlem: `--force` sonrası 0.0/10 vitrin). Üç ileri düzeltme: (1) `auto_chain._run_chained_agent` set_active_job öncesi **taze okuma**; (2) `semantic/rebuild` decision_brief aynası öncesi **taze okuma + expire**; (3) `demo_prefill` akışı = `drain (arka plan görevleri) → _reconcile_suite_context (6 ajan sonucu otoriter job satırlarından) → CEO (`--force`'ta 1 saatlik "recent" guard'ı temizlenir) → read-back doğrulama`; `context_verified=False` veya eksik `last_*_result` → **exit 1**. Kanıt: `--force` koşusunda sıfır yeniden yazım (idempotent), `context_verified: True`.
- [x] **Log paritesi**: `job.result_json` `_jsonable` (derin), context `_serialize_result` (eski: yalnız `.step`/dict) → `AuditStepLog`/`RiskStepLog` dataclass'leri context'e sessizce atılıyordu → her koşuda job≠context "drift". `_serialize_result` logları artık `_jsonable_log` ile aynı biçimde; kapı `test_context_persist_logs.py` (2 test).
- [x] **Yerel demo env**: `frontend/.env.local`'a `NEXT_PUBLIC_DEMO_MODE=true` (gitignored; bayrak yoksa `IS_DEMO` false → dolu-buton + DemoBanner hiç render edilmiyor; D5 compose'ta zorunlu).

### D3 — Rehberli akış (tour) — ÖNCELİK 2
- [ ] 4 adım: (1) CFO özeti & runway, (2) anomali denetimi, (3) CEO brief / çapraz risk, (4) "Şirketinizle deneyin" CTA. Step JSON i18n'de (tr/en).
- [ ] İlk girişte otomatik başlangıç; sidebar'da "Turu tekrarla".
- [ ] auto-chain görünürlüğü (1.6 ile birlikte): demo izleyicisi ajanların çalıştığını görür.

### D4 — Reset + hijyen — ÖNCELİK 2 ✅ (2026-10-15)
- [x] `DELETE /demo/reset` implement (docstring ile hizalı): demo job'ı + context snapshot temizliği. (2026-10-15: `api/demo.py` endpoint + `services/demo_template.py::purge_demo_workspace` = klonun simetriği: DEMO_FILENAME job'ları + sert FK çocuklar (Report/Transaction/Anomaly/DecisionLog), CompanyContextSnapshot (Redis cache dahil) ve semantic snapshot; dosya yalnızca başka job paylaşmıyorsa unlink (clone golden'dan paylaşır → golden dosyası asla silinmez). Golden org 409, `demo_mode` kapalıyken 403, authsuz 401, ikinci çağrı idempotent (sabit sıfır sayaç şekli). Kapı: `test_demo_reset.py` 7 test + canlı: openapi'de rota, konuk reset → counts birebir klon aynası `{reports:2, transactions:163, anomalies:4, semantic:1, context:1}`, `has_demo` True→False, tekrar 0, authsuz 401.)
- [x] Konuk TTL: X saat sonra org data purge (cron/ARQ task) + rate limit (konuk başına günde N seed). (2026-10-15: TTL = `config.demo_guest_ttl_hours=24` + APScheduler saatlik `_demo_guest_ttl_purge` — **demo_mode'a bağlı kayıt** (production'da cron yok; canlı log'da `Added job "_demo_guest_ttl_purge"` doğrulandı) → test edilebilir `_purge_expired_guests(db, ttl_hours)` çekirdeği. Konuk parmak izi = slug `demo-<12hex>` + `GUEST_DESCRIPTION` (tek kaynak) → golden/kayıtlı org asla purge edilmez. Rate limit = middleware route limiti `/api/v1/demo/seed → 5/86400` (kullanıcı JWT'si/IP; idempotent tekrarlar da sayılır). Kapı: TTL filtresi testi (eski konuk gider; eski gerçek org + golden + taze konuk kalır) + 6. istek 429/Retry-After testi.)
- [x] `npm audit` upgrade task'ı gibi: bu iş de yeşil testlerle ayrı sprint'e. (Karar kaydı: uygulanmadı — rutin bağımlılık bakımı ayrı sprint'e ertelendi; D4'ün reset/TTL/limit işi bu sprint'te kapandı.)

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
