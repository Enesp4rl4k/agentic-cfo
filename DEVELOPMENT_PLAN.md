# 🗺️ Geliştirme Planı — Agentic CFO (Birleşik, v2)

> **Tarih:** 2026-10-14 (v1: 2026-10-11) · **Ufuk:** 3 faz (Faz 1 güven turu → Faz 2 moat → Faz 3 production kanıtı)
> **Yasa:** `CLAUDE.md` — Done = `python scripts/verify.py` (Windows) / `./verify.sh` exit 0. Confidence gate ≥ 0.80. Raw SQL yok. Money = kuruş integer.
> **Kuzey yıldızı:** Yüklediğin veri → kanıtlanmış sayı → rol-dashboard'unda org'un dilinde ve **org'un para birimiyle** doğru çizilen tek bir gerçeklik → karar → mühürlü kayıt. Bir halka kanıtlanmadan iş bitmiş sayılmaz.
>
> Bu dosya şunları **yerine geçer (supersedes)**: `MASTER_DEVELOPMENT_PLAN.md`, `NEXT_DEVELOPMENT_PLAN.md`, `DIFFERENTIATION_SPRINT_PLAN.md`, `EXECUTIVE_PANEL_V1_BACKLOG.md`. Bunlar tarihsel kayıt olarak duruyor; yeni iş buradan takip edilir.
>
> **v2 değişikliği:** Faz 1'in A–D grupları bitti; 2026-10-14 canlı doğrulama (CTO/CMO/COO/CHRO/CEO) yeni sorunlar çıkardı → Sorun Envanteri (Kullanıcı U1–U8 / Sistem S1–S6) eklendi, Faz 1'e 1.4–1.6 maddeleri ve "Hemen" dev-flow bölümü girdi. Faz 2/3 değişmedi.

---

## 0. Başlangıç durumu (2026-10-14, kanıtlı)

**Yeşil:**
- `python scripts/verify.py --fast --backend` → exit 0 · **3459 passed, 48 skipped**; frontend `tsc` ✅ `lint` ✅ `vitest` 90/90 ✅.
- Backend: FastAPI + LangGraph, 41 Alembic migration, ARQ kuyruğu, job lease, field encryption, audit zinciri, e-Fatura/e-Defter kapısı, SMMM onay kuyruğu, TCMB EVDS client, grounding validator + `EvidenceBundle`, eval harness, semantic snapshot/rebuild.
- Frontend: Next 14 App Router, Karar Atlası paleti (`DESIGN.md`), TR/EN message tree — **Grup A–D (17 sayfa) message tree'de**.
- Rol matrisi canlı doğrulandı (2026-10-14): **CHRO** (İK Puanı 7.0/10, ₺ anlatıları), **CEO** (synthesize 200, brif dolu), **CMO** (ROAS 3.9×, ₺), **CTO** (hydration + sağlık 2.0/10), **COO** (boş durum dürüst) — 0 undefined / 0 NaN / 0 konsol hatası.
- `org_id` login/me'de dönüyor (regresyon testi `test_api_integration.py`'de); CHRO CTO hydration + İ-casing + sidebar rozet fix'leri commit `712c027`.

**Kırmızı (v2 planın gerekçesi — Sorun Envanteri §1):**
1. Backend anlatı/expanter'larında **33 kalan `$` hardcode** — TRY verisinde dolar (CHRO 3'ü düzeltildi, kalanı yok) → U1.
2. **Hydration UX**: Redis'siz context okuması 15–20sn; form dolarken sonuç gelip formu yutuyor; loading göstergesi yok → U2/S1.
3. **Şema fixture testi yok** (1.2 hâlâ açık): CHRO'daki hata sınıfı CTO/CMO/COO/CEO/risk/audit'te canlı bakıldı ama testi yok → U3.
4. **Grup E i18n** + kalan dinamik rozet/casing taraması → U4.
5. **COO hiç populated olmadı** (örnek SLA CSV yok) → U5.
6. CEO ana buton 400; auto-chain CEO sentezi sessiz skip; health skoru bileşen/overall karışıklığı → U6/U8.
7. Faz 2/3 hiç başlamadı (Playwright, IDOR, security header, TCMB stres, SMMM export) → S3/S4.
8. Dev-flow: backend `--reload` yok, restart secret yeniliyor, branch push edilmedi → S2/S5.

---

## §1 Sorun envanteri

### 🧑 Kullanıcı sorunları

| # | Sorun | Kanıt | Çözüm → madde |
|---|-------|-------|---------------|
| U1 | Backend anlatılarında `$` hardcode (TRY verisinde dolar) | 33 site: `pnl/cashflow/forecast/budget/chat/infra/synthesis/strategic_priorities/loss/campaign/resource/exporters` | **1.4** para birimi süpürmesi + grep kapısı testi |
| U2 | Hydration "şekil kayması" + yükleme göstergesi yok | Log: her context GET'i timeout→DB fallback (~15-20sn) | **1.5** skeleton + kısa timeout |
| U3 | Rol şeması fixture testi yok (undefined basan kart sınıfı) | CHRO'da bulundu, diğerleri canlıda temiz ama testsiz | **1.2** normalizer + gerçek yanıt fixture'ı |
| U4 | Kalan İ-casing + gömülü TR metin | Grup E + tam tarama yapılmadı | **1.1E** + **1.2** grep kapısı |
| U5 | COO populated durumu doğrulanmadı | `last_coo_result: None` | **1.6** örnek SLA CSV + canlı doğrulama |
| U6 | CEO buton 400; auto-chain sessiz skip | Gözlem (synthesize tetikleniyor, sonuç yok) | **1.6** micro-fix'ler |
| U7 | Gerçek/Tahmin/Benchmark ayrımı yok | — | **1.3** provenance bileşeni |
| U8 | Health skoru karıştırıcı (bileşen 10.0 / overall 7.0) | Canlı CHRO | **1.6** açıklama etiketi |

### ⚙️ Sistem sorunları

| # | Sorun | Kanıt | Çözüm → madde |
|---|-------|-------|---------------|
| S1 | Redis'siz her context okuması tam timeout bekliyor | Log'da her GET ~15-20sn | **1.5** 2sn timeout + hemen fallback |
| S2 | Dev'de `--reload` yok; restart `BACKEND_SECRET_KEY` yeniliyor | İki kez canlı test tuzağı + re-login | **Hemen** sabit dev `.env` |
| S3 | Playwright E2E yok; golden path grep ile | Faz 3 başlamadı | **Faz 3.1** |
| S4 | IDOR/encryption/security-header kanıtı yok | Faz 3 başlamadı | **Faz 3.3-3.4** |
| S5 | Branch push edilmedi (5+ commit lokal) | `feat/edefter-tahakkuk` | **Hemen** push + küçük commit ritmi |
| S6 | Kalite denetimi bayat (2026-08-05) | `QUALITY_AUDIT_REPORT.md` | **Hemen** npm audit + ruff/mypy taze tur |

---

## ⚡ Hemen (dev-flow, yarım gün — S2/S5/S6)

- [ ] Backend dev `.env`: sabit `BACKEND_SECRET_KEY` (restart → re-login yok) + uvicorn `--reload`
- [ ] `git push` (remote varsa) — sonrası her iş küçük commit'le
- [ ] `npm audit` + `ruff check` + `mypy` taze tur → sonuç bu dosyaya not edilir

---

## FAZ 1 (Faz 1, Hafta 1–2) — "Arayüz doğru söylüyor" (Güven turu)

**Tema:** Her sayfa, org'un dilinde **ve org'un para birimiyle**, gerçek backend verisiyle çizilsin. Yeni özellik yok; güvensiz metin/veri yok.

### 1.1 i18n tamamlama hattı (sayfa grubu → message tree)
Taşıma kuralı: sabit metin `tr.ts`/`en.ts`'e; iki ağaç anahtar olarak eşit; `i18n.test.ts` her grup için ≥1 TR ve ≥1 EN assertion.

- [x] **Grup A — çekirdek akış:** `baglan`, `upload`, `chat`, `pnl`, `cashflow` — ✅ (2026-10-11): 5 sayfa + `EpostaKutusu`; `₺`/`$` sabit kodu ve USD-default `formatCurrency` → `useCurrencyFormat`+`useCurrencySymbol`; `baglan.test.tsx` `useOrgSettings` mock'u; parite testi eklendi. Kapı: tsc ✅ lint ✅ vitest 92/92.
- [x] **Grup B — finans detayları:** `budget`, `tax`, `trends`, `comparison`, `forecast`, `sensitivity` — ✅ (2026-10-11): 6 sayfa; `₺`/`$`/USD-default sabitler + `toLocaleDateString("tr-TR")` → helper+locale; `comparison` `(p as any)`/`<icon>` ve `budget` cast düzeltmeleri; `%{val}` vs `{val}%` assertion. **Exempt:** `forecast` alert filtresi (backend veri eşlemesi). Kapı: tsc ✅ lint ✅ vitest 93/93.
- [x] **Grup C — operasyon:** `integrations`, `intelligence`, `anomalies`, `reports`, `templates`, `notifications` — ✅ (2026-10-12): 6 sayfa; `ERP_PROVIDER_*` ağaçta; `useRelativeTime` locale'e bağlı; severity/type/rapor etiketleri; `i18n.test.ts` Grup C assertion. **Exempt:** kod yorumları, CSV örnek verisi. Kapı: tsc ✅ lint ✅ vitest 94/94.
- [x] **Grup D — yönetim & muhasebe:** `smmm`, `smmm-onay`, `audit`, `risk`, `risk/cascade`, `simulation`, `iliskili-taraf`, `tr-vertical` — ✅ (2026-10-12): 8 sayfa; yeni namespace `smmm`/`smmmOnay`/`audit`/`risk`(+`cascade`)/`simulation`/`iliskiliTaraf`/`trVertical`; rozetler JS `.toUpperCase()`; Kapı: tsc ✅ lint ✅ vitest 95/95.
- [ ] **Grup E — kalan:** `baslangic`, `kurumsallasma`, `pilot`, `settings/*`, `analytics/*`, `layout.tsx`, `error.tsx`

**DoD (her grup):** sayfada `[çÇğĞıİöÖşŞüÜ]` ile eşleşen gömülü UI metni kalmaz (fixture/CSV örnek verisi ve yorum hariç — `// i18n-exempt` gerekçesiyle). TR org'da TR, EN org'da EN; ilk render'da yanlış dil flash'ı yok. `npx tsc`, `next lint`, vitest yeşil.

### 1.2 Rol dashboard'ları: şema sözleşmesi
CHRO'da düzeltildi sınıfı (UI ↔ backend anahtar uyumsuzluğu) tüm rol sayfalarında sözleşme altına alınır.

- [ ] Her rol sayfası için `lib/<role>-result.ts` normalizer'ı (varsa) ve **"backend ne dönerse o" testi**: gerçek API yanıt fixture'ı (kayıttan alınmış) — `undefined`/`String(undefined)`/`NaN` basamaz. Kapsam: **cto, cmo, coo, ceo, risk, audit** (cfo/chro var).
- [ ] Para her yerde `useCurrencyFormat` + org locale/currency; `₺`-hardcode ve USD-default kalmaz (frontend tarafı Grup A–D'de büyük ölçüde bitti; kalan tarama bu maddede).
- [ ] **Casing grep kapısı:** CSS `text-transform: uppercase` + İngilizce veri token'ı birleşimini arayan test/kontrol (düzeltme kuralı: JS `.toUpperCase()`). Bu hafta düzeltildi: CHRO/CEO/CMO/Command-Center/ConflictCard rozetleri (`87cd317`, `335991e`), CTO severity + component keys + sidebar group labels (`712c027`) — **kalan sayfa taraması + kalıcı kapı bu madde.**

**DoD:** `frontend/src/__tests__/` altında her rol için normalizer/fixture testi; canlı kontrolde 6 rol sayfasında `undefined`/`NaN` basan kart yok; casing kapısı yeşil.

### 1.3 Kanıt/ provenance bileşeni
- [ ] Gerçek · Tahmin · Benchmark ayrımı tek ortak bileşenle (DESIGN.md kuralı) metric kartına iliştirilir; `pnl`, `tax`, `analytics`, `budget` öncelikli.

### 1.4 Para birimi dürüst süpürmesi (U1) — **yeni**
- [ ] `app/core/financial.py`'de tek formatter (kuruş → org para birimi; TR platform varsayılanı ₺, sembol tablosu TRY→₺ / USD→$ / EUR→€).
- [ ] Backend'de kalan **33 `$` sitesi** tek tek sınıflandırılıp düzeltilir: org verisi (pnl, cashflow, forecast, budget, chat_agent, infra, synthesis, strategic_priorities, loss, campaign, resource, exporters) → formatter; **gerçekten USD olanlar allowlist** (`model_gateway` LLM harcaması $, gömülü JS template `ws_alerts`, test fixture'ları).
- [ ] **Grep kapısı testi:** `app/` içinde currency-`$` deseni yalnız allowlist'te olabilir; CHRO anlatıları gibi yeni fallback yazıları da bu kapıdan geçer.

**DoD:** TRY org'unda hiçbir kullanıcıya `$`'lı tutar görünmez; kapı testi yeşil; `pytest tests/ -q` yeşil.

### 1.5 Hydration & yükleme UX'i (U2/S1) — **yeni**
- [ ] Context yüklenirken **skeleton / "Son analiz yükleniyor"** göstergesi; form ve sonuç aynı anda yarışmaz (form, hydrasyon kararına göre gecikmeden açılır).
- [ ] `company_context` Redis okumasında **2sn timeout** → hemen DB fallback (Redis kesintisi 15-20sn'ye değil ~2sn'ye düşer).
- [ ] İpucu: `refetchIntervalInBackground` ile zombi polling kapanır.

**DoD:** Redis yokken sayfa açılıştan ≤3sn'de karar verir; form→sonuç yutması canlıda tekrarlanmaz.

### 1.6 Rol sayfaları doldurma & micro-fix'ler (U5/U6/U8) — **yeni**
- [ ] **COO:** örnek SLA/süreç/kaynak CSV'lerle (CHRO'daki PH gibi) canlı popülasyon + 1.2 fixture'ı.
- [ ] **CEO:** girdi yokken ana buton yönlendirici mesaj versin (400 değil); auto-chain skip'i görünür log/not olarak yazsın.
- [ ] **Health skoru:** kartta "bileşenler kendi ölçeklerinde, genel skor ağırlıklı" açıklaması (10.0 vs 7.0 karışıklığı).

**Faz 1 çıkış kapısı:**
```powershell
python scripts/verify.py          # --fast YOK: mypy da dahil
cd frontend; npx tsc --noEmit; npx next lint; npx vitest run
# + canlı dürüstlük taraması: 6 rol sayfasında undefined/NaN/$/İ-casing = 0
```

---

## FAZ 2 (Sprint 2, Hafta 3–4) — "Moat ve karar döngüsü"

**Tema:** Türkiye'ye özgü derinlik + kanıtlanmış sayısal cevap + çatışma → karar.

### 2.1 TCMB EVDS → canlı stres testi
- [ ] `tcmb_macro` snapshot'ından **Kur/Faiz şok simülatörü**: slider → nakit akışı/FAVÖK etkisi anında.
- [ ] Zorunlu kaynak etiketi (`tcmb_api` / `redis_cache` / `static_fallback`) + "Tahmin" etiketi; fallback asla canlı gibi sunulmaz.
- [ ] Widget `analytics`; TR/EN metin message tree'de.

**DoD:** `EVDS_API_KEY` yokken sayfa çalışır ve "statik fallback" etiketiyle çizilir; şok senaryosu pure-fonksiyon testi yeşil.

### 2.2 Grounding: citation zorunluluğu
- [ ] Embedding yazımı worker'da zorunlu; yükleme sonrası boşsa job `awaitingReview` + log.
- [ ] `/chat/agent` yanıtındaki her sayısal iddia `EvidenceBundle`'a bağlı; bağlanamayan iddia için hard disclaimer.
- [ ] Eval halüsinasyon case'i > 0 → **CI hard-fail** (`eval-grounding.sh` → `verify.py`).

**DoD:** `pytest tests/test_agents/test_grounding_eval.py test_chat_grounding.py -q` yeşil + "citation yoksa uydurma" case'i.

### 2.3 Çatışma → konsensüs → CEO kararı
- [ ] CFO+risk tamamlanınca otomatik `run_consensus` (mevcut `ConsensusEngine`).
- [ ] Command Center **Conflict Card**: severity, çelişen agent'lar, önerilen konsensüs, tek tıkla karara bağlama.
- [ ] `GET /system/ops` → `management.conflicts` sayacı.

**DoD:** Zıt sinyalli fixture'da kart render; resolve sonrası açık çatışma yok. Canlı: `scripts/tr-governance-e2e.sh`.

### 2.4 Semantic spine API kontrat testleri
- [ ] `POST /semantic/me/rebuild` → 200 + metrics > 0; `GET /semantic/me` → `snapshot.period.key`; `GET /semantic/me/brief` → runway+conflict; `GET /negotiation/conflicts/{org}` ORM listesi.

### 2.5 SMMM mühürlü export paketi (moat)
- [ ] Tek tıkla resmi paket: yevmiye dökümü, KDV/stopaj kontrolü, anomaliler, e-Defter berat uyumluluk özeti → PDF + Excel.
- [ ] İmza/metaveri: şirket, dönem, üretim zamanı (UTC), veri kaynakları, "agent üretti, SMMM onayladı" mühür alanı. Otomatik onay yok.

**Faz 2 çıkış kapısı:**
```powershell
python scripts/verify.py
./scripts/tr-governance-e2e.sh
./scripts/smmm-defensibility-smoke.sh
```

---

## FAZ 3 (Sprint 3, Hafta 5–6) — "Production kanıtı"

**Tema:** Tarayıcı seviyesinde uçtan uca kanıt + çoklu pod + sertifikasyon kapıları.

### 3.1 Playwright Golden Path (yeni: `frontend/e2e/`)
1. Login → org seçimi  2. `baglan`/`upload` → CSV → kolon eşleştirme → analiz  3. SSE canlı ilerleme  4. CFO/CEO kartları (`undefined`/`NaN` taraması)  5. Chat → yanıt → kanıt rozeti  6. SMMM onay kuyruğu
- [ ] `npm run e2e` CI'da koşar; yeşil PR kırmazsa sprint kırmızı.
- [ ] `scripts/golden-path-e2e.sh` bu paketi çağırır.

### 3.2 SSE Redis Pub/Sub (multi-pod)
- [ ] `streaming/sse.py`: bellek yerine `org:{org_id}:job:{job_id}` Redis kanalı; iki pod arası event yayını testi.

### 3.3 Tenant izolasyonu denetimi (IDOR/BOLA)
- [ ] `org_id`'li tüm tablolarda otomatik tenant filtresi taraması; negatif test paketi: org B → org A job'ı 404/403.
- [ ] Hassas kolonlarda (VKN, IBAN, API key) field encryption kanıtı: DB'de şifreli, bellekte net.

### 3.4 Güvenlik & config sertleştirme
- [ ] Prod'da insecure `BACKEND_SECRET_KEY` default → exception (testte kalır).
- [ ] Security headers (CSP, HSTS, X-Content-Type-Options, X-Frame-Options) + test.
- [ ] ARQ analysis/maintenance ayrımının uygulandığını gösteren test (yeni queue mimarisi yok).

### 3.5 Yük & gözlemlenebilirlik
- [ ] `./scripts/load-baseline.sh` CI artifact'i; P95: upload→analiz başlangıcı, board deck < 120s.
- [ ] `/system/ops`: LLM maliyeti, failed job oranı, awaiting-review yükü.

**Faz 3 çıkış kapısı (release adayı):**
```powershell
python scripts/verify.py
cd frontend; npm run e2e
./scripts/golden-path-e2e.sh
BACKEND_URL=http://localhost:8000 ./scripts/staging-smoke.sh
```

---

## Kapsam dışı (bu döngüde bilinçli olarak YOK)

- Yeni C-level rol (CPO, CLO, …).
- Kafka / sub-100ms hedefleri, LangGraph major upgrade.
- Yeni dashboard sayfası açmak (var olanı doğru çizmek yeni sayfadan önce gelir).
- Geniş TR parser kapsamı (mevcut: Logo Tiger, Paraşüt, GİB e-Fatura yeterli).
- Çoklu-para birimi tam plumbing (kur varsayılanı ₺; sembol tablosu hazır, org-bazlı seçim ileride).

## Mimariyi bozmayan kurallar

1. i18n → sadece metin taşır; layout/veri akışı değişmez.
2. Conflict/consensus → mevcut `ConsensusEngine` + negotiation API; yeni silo yok.
3. RAG → sadece retriever implementasyonu/imza; API sabit.
4. Her agent run → `JobLog`/`StepLog`; verify eden, hesaplayanın kendisi değil.
5. `backend/app/agents/` değişti → `pytest tests/test_agents/ -q` zorunlu. Model değişti → Alembic migration zorunlu.
6. Para → tek formatter (`app/core/financial.py`); yeni `$`/`₺` hardcode yasak (grep kapısı).

## Riskler

| Risk | Mitigasyon |
|------|-----------|
| Grup E + 1.2 + 1.4 aynı sprint'i patlatır | Sıra: Hemen → 1.4 → 1.2 → 1.5 → 1.6 → 1.1E; her madde ayrı commit + kendi DoD'su |
| 33 `$` sitesi arasında yanlış sınıflandırma (gerçek USD'li allowlist) | Site-site gözden geçirme + allowlist'i testte sabitleme |
| EVDS API anahtarı / erişim yok | 3 katmanlı fallback + kaynak etiketi zorunlu |
| Playwright CI'da flaky | İlk sprint sadece golden path, retry 0, locator bekleme |
| pgvector yoksa embedding'ler boş | Nullable kalır; boş kalınca job → `awaitingReview` |

## Günlük ritim

```powershell
# her gün, yeni işe başmadan
python scripts/verify.py --fast --backend
cd frontend; npx vitest run
```

- Backend dev sunucusu `--reload` + sabit `.env` secret ile (Hemen maddesi) — restart'ta oturum kopmaz.
- Yeşil değilse sprint kırmızıdır. Yeni UI, kanıtlanmış eski UI'dan önce ilerleme değildir.
