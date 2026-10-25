# 🗺️ Geliştirme Planı — Agentic CFO (Birleşik, v5)

> **Demo deneyimi ayrı planda:** `DEMO_PLAN.md` (2026-10-14) — "satın almadan dene" akışı: mevcut envanter + boşluklar + D1–D6 fazları (konuk giriş → anında dolu dashboard → tour → reset → public → CTA).

> **Tarih:** 2026-10-23 (v4: 2026-10-21, v3: 2026-10-17, v2: 2026-10-14, v1: 2026-10-11) · **Ufuk:** **§V5** — DDIA ilkeleriyle şirket düzeyinde veri omurgası (tek defter → olay günlüğü → yeniden kurulabilir görünümler) ve bunun üstüne gerçek kullanıcı faydası (düzeltmelerin kalıcılığı, sürekli defter, tahmin isabeti, dönem kapanışı). §V4 ve Faz 2/3 maddeleri §V5 sırasına yerleştirildi.
> **Yasa:** `CLAUDE.md` — Done = `python scripts/verify.py` (Windows) / `./verify.sh` exit 0. Confidence gate ≥ 0.80. Raw SQL yok. Money = kuruş integer.
> **Kuzey yıldızı:** Yüklediğin veri → kanıtlanmış sayı → rol-dashboard'unda org'un dilinde ve **org'un para birimiyle** doğru çizilen tek bir gerçeklik → karar → mühürlü kayıt. Bir halka kanıtlanmadan iş bitmiş sayılmaz.
>
> Bu dosya şunları **yerine geçer (supersedes)**: `MASTER_DEVELOPMENT_PLAN.md`, `NEXT_DEVELOPMENT_PLAN.md`, `DIFFERENTIATION_SPRINT_PLAN.md`, `EXECUTIVE_PANEL_V1_BACKLOG.md`. Bunlar tarihsel kayıt olarak duruyor; yeni iş buradan takip edilir.
>
> **v2 değişikliği:** Faz 1'in A–D grupları bitti; 2026-10-14 canlı doğrulama (CTO/CMO/COO/CHRO/CEO) yeni sorunlar çıkardı → Sorun Envanteri (Kullanıcı U1–U8 / Sistem S1–S6) eklendi, Faz 1'e 1.4–1.6 maddeleri ve "Hemen" dev-flow bölümü girdi. Faz 2/3 değişmedi.
>
> **v3 değişikliği (2026-10-17):** **Faz 1 kapandı** (çıkış kapısı 2026-10-15'te geçti: `verify.py` 6/6, vitest 154/154, canlı scan 10/10 — U1–U8 + S1/S2/S5 hepsi çözüldü). `DEMO_PLAN.md`'den **D1 ✅ D2 ✅ D4 ✅** devralındı; kalan açık işler: **D3 (tur) → Faz 2 (moat) → D5+D6 (demo dağıtım/dönüşüm) → Faz 3 (production kanıtı)** + iki bakım görevi (prod `next` upgrade, `tests/` ruff temizliği). S3/S4 (Playwright, IDOR/security) hâlâ açık — Faz 3'te.
>
> **v4 değişikliği (2026-10-21):** v3 kodun gerisinde kalmıştı. Kod taraması: Faz 2/3'ün "hiç başlamadı" dediği maddelerin çoğu **kısmen ya da tamamen kodda** (2.1 stres kartı, 2.3 otomatik konsensüs + `ConflictCard` + ops sayacı, 2.4 kontrat testi, 2.6 tur bileşeni, 3.2 SSE Redis pub/sub, 3.4 güvenlik başlıkları + güvensiz secret kontrolü) — her maddeye **"Kodda durum"** notu eklendi. Plan dışı yapılan **P4 tetik motoru** (P4-0…P4-4, 2026-10-18…20) plana alındı; boşluğu: `anomaly.detected` ve `schedule` olaylarının kaynağı yok. Yeni öncelik sırası **§V4**: önce sessiz yanlışlar (çalışmayan tetik, yanlış EUR şoku, kapı kapsamı), sonra yeni yetenek.
>
> **v5 değişikliği (2026-10-23):** V0–V2 kapandı (PR #4 birleşti, PR #5 açık). `DDIA_COMPLIANCE.md` iş (job) düzeyini sağlam gösteriyor — atomik claim, lease, reaper, idempotent yeniden hesaplama. Ama kod taraması **şirket düzeyinde** veri omurgasının olmadığını gösterdi ve bu doğrudan kullanıcı faydasını kırıyor: her yükleme bir ada (çift sayım), kullanıcı düzeltmeleri hiç uygulanmıyor, olaylar çökmede kayboluyor, tahminler hiç ölçülmüyor. **§V5** bunu DDIA bölümleriyle eşleyip sıralar.

---

## §V5 — DDIA ile veri omurgası ve gerçek fayda (2026-10-23)

**Tez (DDIA Ch.11–12, "derived data"):** Bir sistemde *tek* kayıt sistemi (system of record) olmalı; geri kalan her şey (dashboard, CompanyContext, semantic snapshot, tetik değerlendirmesi, rapor) ondan **türetilmiş, yeniden kurulabilir** görünüm olmalı. Bugün kayıt sistemi parçalı: her analiz kendi `Transaction` adasını taşıyor, şirket düzeyindeki `canonical_transactions`'ı yalnız ERP senkronu besliyor. Kullanıcı açısından sonuç: "şirketimin tek, sürekli, güvenilir defteri" yok — her ay sıfırdan başlıyor.

### Kanıtlı boşluklar (2026-10-23 kod taraması)

| # | Boşluk | Kanıt | Kullanıcıya etkisi | DDIA |
|---|---|---|---|---|
| G1 | **Kullanıcı düzeltmeleri uygulanmıyor** | `api/corrections.py` yalnız `classifier.learn()` çağırıyor; `services/classifier.classify()` (CategoryRule uygulayan) hiçbir ingest yolunda çağrılmıyor | Aynı satıcıyı her ay yeniden düzeltiyor; "öğrenen sistem" vaadi boş | Ch.11 — kullanıcı girdisi de bir olay; türetilmiş sınıflandırma onu tüketmeli |
| G2 | **Her yükleme bir ada, tekilleştirme yok** | `models/transaction.py`: yalnız `job_id`, `org_id`/içerik parmak izi/benzersizlik kısıtı yok; `islemleri_ekle` (Paraşüt, e-posta) her seferinde yeni job | Aynı dosya iki kez → iki kat gelir; çakışan ekstreler çift sayılır; ay ay sürekli görünüm yok | Ch.2/Ch.11 — tek kayıt sistemi; Ch.7 — idempotent yazma |
| G3 | **İki kayıt sistemi** | `canonical_transactions`'a yalnız `scheduled_sync` yazıyor; `semantic/rebuild` canonical'dan, dashboard job `Transaction`'ından okuyor | ERP'li ve dosyalı şirketin sayıları farklı yoldan gelir; tutarsızlık sessiz | Ch.11 — "unbundling": tek log, çok görünüm |
| G4 | **Dual-write / olay kaybı** | `worker.continue_after_completion`: commit sonrası tetik/bağlam/semantic `spawn(...)` ile süreç içi ateşle-unut | Süreç commit ile yayın arasında ölürse tetik ateşlenmez, bağlam eskir — kimse fark etmez | Ch.11 — transactional outbox / CDC |
| G5 | **Tüm-satır JSON bağlam** | `CompanyContextSnapshot.context_json` okuma-değiştirme-yazma; kayıp güncelleme 2026-10-14'te "taze okuma" yamasıyla örtüldü | Eşzamanlı ajanlar birbirinin sonucunu silebilir (gözlendi: 0.0/10 vitrin) | Ch.7 — lost update; optimistic concurrency |
| G6 | **Tahminler ölçülmüyor** | tahmin/öngörü saklayan model yok | "Runway 8 ay" diyoruz ama geçen ayki tahminimiz ne kadar tuttu bilinmiyor; güven kalibre değil | Ch.10 — batch: geçmiş üzerinde değerlendirme |
| G7 | **Dönem kavramı yok** | kapanış/kilit modeli yok | Geçmiş ay sessizce değişebilir; SMMM'ye "bu ay kapandı" denemez | Ch.12 — immutability, audit |
| G8 | Operasyon gözlemlenebilirliği | Prometheus/metrik yok, `OFFSET` pagination, prod backup/PITR runbook yok | Arıza önce kullanıcıdan duyulur | Ch.1/5/6/8 |
| G9 | Gizlilik açıkları (sahip kararı) | `audit_log` org_id/retention yok; alan şifrelemesi default değil; legacy düz metin API key | KVKK talebine (sil/dışa aktar) cevap verilemez | Ch.12 |

### Fazlar

> Her faz: ayrı branch/PR, kendi DoD'u, `verify.py` exit 0 olmadan commit yok. Model değişen fazlarda Alembic migration zorunlu; kolon/tablo **düşüren** migration DISPATCH (önce sahibe sorulur) — bu plan hiçbir şey düşürmez, yalnız ekler ve backfill yapar.

#### F0 — Düzeltme döngüsünü kapat (G1) · ~1 gün · en yüksek fayda/maliyet
- [x] Tüm ingest yolları kullanıcının kurallarını uygular. Tasarım: kurallar çağıran tarafta **bir kez** yüklenir (`classifier.load_rules`, yalnız "her zaman uygula" olanlar), bellekte eşleşir (`apply_rules`: satıcı alanı **veya** açıklamadaki satıcı adı — banka ekstresi —, sonra anahtar kelime; Türkçe katlama), isabetler satırlarla aynı transaction'da sayılır (`record_hits`). İki dikiş tüm yolları kapsar: (1) pipeline'ın `data_ingestion` düğümü — dosya, e-posta, Paraşüt ve ERP-CSV hepsi `islemleri_ekle` → job → worker yolundan geçer; (2) `scheduled_sync` — zamanlanmış ERP satırları canonical'a yazılmadan önce. `transactions.category_source` (`user_rule` / `user_edit`, migration 043). Eski tek-satır `classify()` (işlem başına sorgu + commit) toplu yolda kullanılmıyor.
- [x] **Yan bulgu, düzeltildi:** worker `run_cfo_pipeline`'ı hiç `org_id` vermeden çağırıyordu → pipeline'daki org'a bağlı her adım (ajan belleği dahil) worker yolunda sahipsiz çalışıyordu.
- [x] ~~Açık job'lardaki satırları yerinde yeniden sınıfla~~ → **yeniden hesaplama** (Ch.10): elle yamanan türetilmiş satır kaynağından sapar, dashboard eski kalır. "Her zaman uygula" düzeltmesi etkilenen bitmiş analizleri döndürür (`affected_job_ids`, düzeltilen iş dahil); yeni `POST /analysis/{id}/rerun` bitmiş/başarısız işi atomik olarak yeniden açıp kuyruğa alır (`job_state.reopen_for_rerun`); incelemedeki ve **SMMM paketi mühürlü** iş reddedilir (409). Tek seferlik (her-zaman-değil) düzeltme yalnız o satırı değiştirir; yeniden hesaplamada korunması satır parmak izi ister → **F1'e taşındı**.
- [x] UI: `/transactions`'ta "Kuralın" / "Elle" rozeti + "Kuralın N analizi etkiliyor → Analizleri yeniden çalıştır" banner'ı (`components/transactions/RuleFeedback.tsx`, tr/en). Not: kullanılmayan `components/transactions/CategoryCell.tsx` kapısı olmayan ölü bileşen (canlı akış sayfadaki `CategoryEditor`).
- [ ] `/ayarlar/kurallar` listesi (kuralları gör/sil) — bu turda yapılmadı.
- **DoD:** ✅ `tests/test_category_rules_apply.py` 18 test (eşleştirici, yalnız standing kurallar, düğüm, worker org+kural+kaynak+isabet, düzeltme→etkilenen işler, tek seferlik düzeltme, rerun: kuyruk / inceleme 409 / mühür 409 / sahiplik, her ingest dikişinin kural uyguladığını gösteren kapı) + `rule-feedback.test.tsx`. Canlı (SQLite dev, konuk org, gerçek pipeline): düzeltme → `affected_job_ids` → rerun → `completed`, satır `user_rule` ile yeniden üretildi, log "1 transaction(s) categorised by 1 user rule(s)"; UI'da banner + rozet görüldü. Sınır: zamanlanmış senkron dikişi yapısal kapıyla korunuyor, davranışsal test yok (`run()` çok katmanlı).
- **Ayrı bulgu (F0 dışı):** `/transactions` TRY verisini `$9,799,500` gibi dolar işaretiyle gösteriyor (sayfa `formatCurrency` USD varsayılanı) — ₺ süpürmesi bu sayfayı kaçırmış.

#### F1 — Tek defter: şirket düzeyinde kayıt sistemi (G2, G3) · ~1–1,5 hafta · omurga
- [ ] `canonical_transactions` tek kayıt sistemi olur: **her** ingest yolu buraya `append` eder. Satır kimliği = `org_id + kaynak + kaynak_belge_id` (varsa: e-Fatura UUID, banka referansı, ERP id), yoksa **içerik parmak izi** `sha256(org, tarih, tutar_kurus, yön, normalize(açıklama/satıcı))`. Benzersizlik kısıtı → aynı dosya ikinci kez = 0 yeni satır (Ch.7 idempotent yazma; `ON CONFLICT DO NOTHING` ORM upsert ile, raw SQL yok).
- [ ] Belirsiz eşleşme (aynı gün, aynı tutar, farklı açıklama) silinmez/birleştirilmez → `possible_duplicate` işaretli, kullanıcı onayına düşer (insan kapısı; confidence gate ilkesi).
- [ ] `Transaction` (job) bir **görünüm** olur: analiz = "şu dönem aralığındaki defter satırları". Geçişte job tabloları kalır (düşürme yok); yeni job'lar defterden türetilir, eskiler backfill ile deftere taşınır (migration + yeniden çalıştırılabilir backfill scripti).
- [ ] Yükleme yanıtı ne olduğunu söyler: "312 satır: 290 yeni, 20 zaten defterde, 2 olası mükerrer (onay bekliyor)".
- **DoD:** (a) aynı CSV iki kez → gelir değişmez; (b) Ocak–Mart + Şubat–Nisan ekstreleri → Şubat–Mart bir kez sayılır; (c) ERP ve dosya yolu aynı dönem için aynı toplamı verir; (d) backfill iki kez çalışınca ikinci koşu 0 satır yazar. Canlı: demo org'da tekrar yükleme kanıtı.

#### F2 — Olay günlüğü + transactional outbox (G4) · ~1 hafta
- [ ] `domain_events` tablosu (append-only: `id`, `org_id`, `kind`, `aggregate_id`, `payload`, `created_at`). Durum değişikliği ile **aynı transaction'da** yazılır: `ledger.appended`, `job.completed`, `anomaly.detected`, `correction.made`, `period.closed`.
- [ ] Relay (scheduler + `_exclusive`, ARQ varsa ARQ): tüketici başına `consumer_offsets` ile en-az-bir-kez teslim; tüketiciler idempotent (tetikler zaten `event_ref` ile; bağlam/semantic projeksiyonları olay id'siyle).
- [ ] `continue_after_completion` içindeki `spawn` zinciri olay tüketicilerine taşınır (tetik, bağlam, semantic, cache invalidation).
- **DoD:** commit sonrası, yayından önce süreç öldürülür → yeniden başlatmada olay yine teslim edilir (test); aynı olay iki kez teslim → yan etki bir kez; relay gecikmesi ölçülür (F6 metriği).

#### F3 — Yeniden kurulabilir görünümler (G5) · ~1 hafta
- [ ] CompanyContext tüm-satır JSON yerine anahtar başına satır: `context_entries(org_id, key, value, version, source_event_id)`; yazma `WHERE version = :beklenen` ile (optimistic concurrency, Ch.7) — kayıp güncelleme yapısal olarak imkânsız.
- [ ] `rebuild --org <id>`: defter + olay günlüğünden bağlam/semantic/dashboard'u sıfırdan üretir; **drift denetimi** gecelik — saklanan projeksiyon ile yeniden hesap farklıysa uyarı (Ch.12 "doğruluğu doğrula, varsayma").
- **DoD:** iki oturum aynı anda farklı ajan sonucu yazar → ikisi de kalır (test); `rebuild` iki kez → bayt-eş çıktı; demo golden prefill bu yola taşınır (`_reconcile_suite_context` yaması emekli olur).

#### F4 — Tahmin defteri ve kalibrasyon (G6) · ~1 hafta · farklılaştırıcı (#2)
- [ ] `forecast_records` (değişmez): metrik, ufuk, tahmin değeri + aralık, model/prompt sürümü, girdi parmak izi, `as_of`. Her CFO/forecast koşusu yazar.
- [ ] Gecelik batch (Ch.10): vadesi dolan tahminleri defterdeki gerçekleşenle notlar (`forecast_grades`); idempotent (aynı tahmin iki kez notlanmaz).
- [ ] UI: "Runway tahminlerimiz sizin için ortalama +1,8 ay iyimser" — org başına hata ve yön; ProvenanceBadge "Tahmin" kartına isabet satırı. Confidence gate eşiği kalibrasyondan beslenir (gate gevşetilmez, yalnız kanıtla daraltılır).
- **DoD:** demo verisinde geriye dönük test (ilk 6 ay ile tahmin → sonraki 6 ay ile not); notlama iki kez → aynı sonuç; isabet satırı veri yokken "henüz ölçülmedi" der (uydurma yok).

#### F5 — Dönem kapanışı, tazelik ve eksik veri (G7) · ~1 hafta · SMMM/kurumsallaşma değeri
- [ ] Ay kapanışı: dönem kilitlenir → o dönemin defter/rapor özeti SHA-256 ile mühürlenir (`DefensibilityPacket` deseni); kilitli döneme sonradan gelen satır **düzeltme kaydı** olarak sonraki döneme yazılır (muhasebe gibi append-only, Ch.12).
- [ ] Kaynak tazeliği: her bağlantı/yükleme için "son veri", "gecikme", "eksik ay" göstergesi; eksik ay listesi `/baslangic` ve Kurumsallaşma Endeksi'ne (process_cadence) girer.
- [ ] Tetik motoruna `period.closed` olayı + "dönem kapanmadı" `schedule` kuralı şablonu.
- **DoD:** kilitli dönem sessizce değişemez (test: kilitli döneme satır → düzeltme kaydı); mühür yeniden hesaplanınca eşleşir; tazelik göstergesi veri yokken "bilinmiyor" der.

#### F6 — Operasyonel dayanıklılık (G8) · paralel iz
- [ ] Prometheus metrikleri: kuyruk derinliği, relay gecikmesi (F2), projeksiyon drift sayısı (F3), job başarı oranı/p95 (`/runs/slo` zaten var → dışa aktar).
- [ ] Keyset pagination (`api/analysis.py` listeleri ilk), `OFFSET` kaldırılır.
- [ ] Postgres yedek + PITR runbook ve **geri yükleme tatbikatı** (yedek, geri yüklenene kadar yedek değildir).
- [ ] Playwright golden path (eski 3.1): yükle → defter → analiz → düzelt → yeniden yükle (F0/F1 akışını uçtan uca kanıtlar).
- Not: Docker/Postgres/Redis bu makinede yok (2026-08-31 kararı) → iki-pod SSE, relay'in çok süreçli testi ve PITR tatbikatı ya CI'da ya Docker kararından sonra. **Sahip kararı.**

#### F7 — Güven ve gizlilik (G9) · sahip kararları
- [ ] `audit_log` + `domain_events` org_id + saklama politikası (öneri: denetim kayıtları 10 yıl — TTK md. 82 saklama süresi, VUK md. 253'ün 5 yılını da kapsar; uygulama logları 90 gün — sahip/hukuk onayıyla).
- [ ] KVKK: org başına **dışa aktar** ve **sil** — defter + olaylar + türetilmiş görünümler; olay günlüğü sayesinde "nereye kopyalandı" izlenebilir.
- [ ] Alan şifrelemesi (VKN, IBAN) default açık + mevcut satırlar için backfill.
- [ ] Legacy düz metin X-API-Key kaldırılır (auth → **DISPATCH**).

### Sıra ve gerekçe

**F0 → F1 → F2 → F3 → F4 → F5**, F6 ve F7 paralel iz.
- F0 bir günde biter ve kullanıcının her ay hissettiği bir acıyı kaldırır.
- F1 her şeyin zemini: tek defter olmadan tahmin notlama (F4) neye karşı notlayacağını, dönem kapanışı (F5) neyi kilitleyeceğini bilmez.
- F2, F3'ten önce gelir: görünümler olaylardan kurulacak.
- Eski açık maddeler şuraya yerleşir: **2.2 grounding** F1'den sonra (her sayı defter satırına bağlanabilir hâle gelir) · **2.5 SMMM paketi** F5'in mührüyle birleşir · **2.6 tur + V2b i18n göçü** bağımsız, ara işler · **3.1 Playwright** F6 · **D5/D6** F1 sonrası (public demo tek deftere dayanmalı).

### Kapsam dışı (bu döngüde)
- Kafka/harici akış altyapısı: `domain_events` + relay, bu ölçekte DDIA'nın önerdiği "veritabanı içinde log" yaklaşımı (Ch.11) — dışa taşıma ölçek gerçekten isterse.
- Çok bölgeli replikasyon, sharding: tek writer Postgres yeterli (Ch.5/6); önce yedek/PITR.
- Event sourcing'in tamamı (her durumu olaylardan türetmek): yalnız defter ve olay günlüğü; job yaşam döngüsü bugünkü atomik claim/finish ile kalır.

---

## 0. Başlangıç durumu (2026-10-21, kanıtlı)

**Yeşil:**
- **2026-10-21:** `python scripts/verify.py --fast --backend` → exit 0 · **3601 passed, 48 skipped**, ruff ✅ (mypy + frontend bu koşuda atlandı).
- P4 tetik motoru: koşul DSL'i + zarf kontratı (P4-0), `trigger_definitions`/`trigger_runs` + idempotency/cooldown/audit (P4-1, migration 042), webhook/analysis/cascade/report aksiyonları (P4-2), `job.completed`/`tx.arrived` kaynakları (P4-3), `/tetikler` API + UI + dry-run (P4-4).
- 2026-10-17: `python scripts/verify.py --fast --backend` → exit 0 · **3459 passed, 48 skipped**; frontend `tsc` ✅ `lint` ✅ `vitest` 95/95 ✅ (90 değil: `baslangic.test.tsx` 6 testi `718a663`'ten beri gizli kırmızıydı — QueryClientProvider + tr-TR locale mock eklendi). **Faz 1 çıkış kapısı 2026-10-15: `verify.py` 6/6, vitest 154/154, `scan_demo_pages.py` 10/10 temiz.**
- Backend: FastAPI + LangGraph, 41 Alembic migration, ARQ kuyruğu, job lease, field encryption, audit zinciri, e-Fatura/e-Defter kapısı, SMMM onay kuyruğu, TCMB EVDS client, grounding validator + `EvidenceBundle`, eval harness, semantic snapshot/rebuild.
- Frontend: Next 14 App Router, Karar Atlası paleti (`DESIGN.md`), TR/EN message tree — **tüm sayfalar (Grup A–E) message tree'de**; 6/6 rol normalizer + wire-fixture testi; `casing-gate.test.ts` + `test_honesty_currency.py` grep kapıları ayakta; `ProvenanceBadge` (Gerçek/Tahmin/Benchmark) tek bileşen.
- Hydration: context 2sn timeout + 30sn cooldown, `HydrationHint`, zombi polling kapalı. CEO no-input guard, auto-chain skip log'ları, COO canlı popülasyon.
- **DEMO (D1+D2+D4):** konuk girişi (`POST /demo/guest` + csrf-race tek yeniden deneme), golden ön-hesaplama (`demo_prefill.py`, 8/8 dolu) + klonlama (izolasyon korunuyor), CTO örnek girdileri + 6 rol IS_DEMO wire-fixture, `DELETE /demo/reset` + 24sa TTL purge + seed rate-limit, `scan_demo_pages.py` canlı tarama aracı.

**Açık (v4 planın gerekçesi — 2026-10-21 kod taraması):**
1. **Hijyen:** v3 plan düzenlemeleri commit'lenmemişti; `feat/edefter-tahakkuk` master'ın **38 commit** önünde, birleşmemiş. → **V0**
2. **P4 sessiz boşluk:** `EventKind` = `job.completed | tx.arrived | anomaly.detected | schedule`, ama yalnız ilk ikisinin kaynağı var → kullanıcı `anomaly.detected`/`schedule` tetiği kurabiliyor, tetik hiç ateşlenmiyor. → **V1**
3. **Dürüstlük hataları:** `MacroStressTestCard` EUR şokuna USD değerini gönderiyor (`eur_shock_pct: usd`), gömülü TR metin, kaynak etiketi yok; `casing-gate.test.ts` yalnız `(dashboard)/*/page.tsx` tarıyor → bileşenlerdeki gömülü TR (stres kartı, `product-tour.tsx`) kapıdan kaçıyor. → **V2**
4. **Faz 2 gerçek boşlukları:** 2.2 grounding/citation zorunluluğu, 2.5 SMMM paketinin genişletilmesi, 2.6 turun demo akışına uyarlanması, 2.3'ün canlı doğrulaması. → **2.x**
5. **Faz 3 gerçek boşlukları:** Playwright E2E (**S3**), şifreleme kanıtı, iki-pod SSE testi, load baseline. → **3.x**
6. **DEMO D5+D6** — public demo ortamı + CTA/lead ölçümü yok. → **3.6–3.7**
7. **Bakım:** prod'da kalan 2 npm açığı (`next` critical + gömülü `postcss` high) yalnız **next 14→16 major** ile kapanır; `QUALITY_AUDIT_REPORT.md` bayat. (`tests/` ruff ✅ `9ea3854`; axios/source-map-js ✅ `89007eb`.) → **Bakım sprinti**
8. **Sahip kararları (hafızadan, ~1 aydır açık — yeniden doğrulanmalı):** → **§Sahip kararları**

---

## §1 Sorun envanteri

> **v3 notu:** U1–U8 + S1/S2/S5/S6 kapandı — tablolar tarihsel kayıt olarak duruyor. Açık maddeler: **S3 → Faz 3.1**, **S4 → Faz 3.3–3.4**.

### 🧑 Kullanıcı sorunları

| # | Sorun | Kanıt | Çözüm → madde |
|---|-------|-------|---------------|
| U1 | Backend anlatılarında `$` hardcode (TRY verisinde dolar) | 33 site: `pnl/cashflow/forecast/budget/chat/infra/synthesis/strategic_priorities/loss/campaign/resource/exporters` | **1.4** para birimi süpürmesi + grep kapısı testi |
| U2 | Hydration "şekil kayması" + yükleme göstergesi yok | Log: her context GET'i timeout→DB fallback (~15-20sn) | **1.5** skeleton + kısa timeout |
| U3 | Rol şeması fixture testi yok (undefined basan kart sınıfı) | CHRO'da bulundu, diğerleri canlıda temiz ama testsiz | ~~**1.2** normalizer + gerçek yanıt fixture'ı~~ **Kapandı** (6/6 rol normalizer + fixture testi) |
| U4 | Kalan İ-casing + gömülü TR metin | Grup E + tam tarama yapılmadı | **1.1E** + **1.2** grep kapısı → **kapandı** (`casing-gate.test.ts`) |
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

## ⚡ Hemen (dev-flow) — ✅ kapandı (2026-10-14)

- [x] Backend dev `.env`: sabit `BACKEND_SECRET_KEY` (restart → re-login yok) + uvicorn `--reload` (2026-10-14: `backend/.env` oluşturuldu, gitignore'lu)
- [x] `git push` ✓ (origin `feat/edefter-tahakkuk` güncel) — sonrası her iş küçük commit'le
- [x] `npm audit` + `ruff check` + `mypy` taze tur (2026-10-14):
  - `ruff check app` ✅ · `mypy --config-file mypy_strict.ini` ✅ (162 dosya). `tests/` içinde ruff'ın 53 legacy hatası var — kapı dışı, temizlik görevi.
  - npm audit: **23 (4 critical, 14 high) dev-only zincirler** (vitest/tinypool/eslint/tailwind); **prod'da 2** (`next` zinciri, 1 critical + 1 high). → **Ayrı task:** prod `next` patch upgrade + vitest 5 migration ile birlikte; `npm audit fix` (non-breaking) 4 kritik kapattı ama lock HEAD'te tutuldu (tek seferde, testler yeşilken upgrade).
  - vitest: 6 test kırmızı çıktı (`No QueryClient set` + TR/EN assertion) → `baslangic.test.tsx`'e QueryClientProvider + `useOrgSettings` tr-TR mock'u eklendi; **95/95** ✅.

## 🔧 Bakım sprinti (plan dışı, düşük öncelik — bir ara oturumda)

- [ ] **Prod npm vulnerability upgrade**: `next` zinciri (1 critical + 1 high) — 14.x/15.x'te yama yok (`89007eb` notu) → **next 14→16 major migration**; vitest 5 migration ile **tek seferde**, testler yeşilken; lock tek commit'te; upgrade sonrası tam kapı (`tsc`/`lint`/`vitest`/`verify.py`).
- [x] **`backend/tests/` ruff temizliği**: 53 legacy hata → ✅ `9ea3854` + `32da052`; `tests/` artık `verify.py` kapısında.
- [x] **Prod axios/source-map-js açıkları** → ✅ `89007eb` (non-breaking `npm audit fix`).
- [ ] **Taze kalite denetimi**: `QUALITY_AUDIT_REPORT.md` (2026-08-05) bayat → npm audit + ruff/mypy turlarıyla güncelle.

---

## FAZ 1 (Faz 1, Hafta 1–2) — "Arayüz doğru söylüyor" (Güven turu)

**Tema:** Her sayfa, org'un dilinde **ve org'un para birimiyle**, gerçek backend verisiyle çizilsin. Yeni özellik yok; güvensiz metin/veri yok.

### 1.1 i18n tamamlama hattı (sayfa grubu → message tree)
Taşıma kuralı: sabit metin `tr.ts`/`en.ts`'e; iki ağaç anahtar olarak eşit; `i18n.test.ts` her grup için ≥1 TR ve ≥1 EN assertion.

- [x] **Grup A — çekirdek akış:** `baglan`, `upload`, `chat`, `pnl`, `cashflow` — ✅ (2026-10-11): 5 sayfa + `EpostaKutusu`; `₺`/`$` sabit kodu ve USD-default `formatCurrency` → `useCurrencyFormat`+`useCurrencySymbol`; `baglan.test.tsx` `useOrgSettings` mock'u; parite testi eklendi. Kapı: tsc ✅ lint ✅ vitest 92/92.
- [x] **Grup B — finans detayları:** `budget`, `tax`, `trends`, `comparison`, `forecast`, `sensitivity` — ✅ (2026-10-11): 6 sayfa; `₺`/`$`/USD-default sabitler + `toLocaleDateString("tr-TR")` → helper+locale; `comparison` `(p as any)`/`<icon>` ve `budget` cast düzeltmeleri; `%{val}` vs `{val}%` assertion. **Exempt:** `forecast` alert filtresi (backend veri eşlemesi). Kapı: tsc ✅ lint ✅ vitest 93/93.
- [x] **Grup C — operasyon:** `integrations`, `intelligence`, `anomalies`, `reports`, `templates`, `notifications` — ✅ (2026-10-12): 6 sayfa; `ERP_PROVIDER_*` ağaçta; `useRelativeTime` locale'e bağlı; severity/type/rapor etiketleri; `i18n.test.ts` Grup C assertion. **Exempt:** kod yorumları, CSV örnek verisi. Kapı: tsc ✅ lint ✅ vitest 94/94.
- [x] **Grup D — yönetim & muhasebe:** `smmm`, `smmm-onay`, `audit`, `risk`, `risk/cascade`, `simulation`, `iliskili-taraf`, `tr-vertical` — ✅ (2026-10-12): 8 sayfa; yeni namespace `smmm`/`smmmOnay`/`audit`/`risk`(+`cascade`)/`simulation`/`iliskiliTaraf`/`trVertical`; rozetler JS `.toUpperCase()`; Kapı: tsc ✅ lint ✅ vitest 95/95.
- [x] **Grup E — kalan:** `baslangic`, `kurumsallasma`, `pilot`, `settings/*`, `analytics/*`, `layout.tsx`, `error.tsx` — ✅ (2026-10-14, önceki oturumdan devralınan in-flight batch commit'lendi): 30+ sayfa message tree'ye + `useCurrencyFormat`'a taşındı; **tam ağaç parite testi** eklendi (`collectLeafPaths` — her iki ağaçta da aynı anahtarlar, string leaf; `i18n.test.ts` +194 satır). DoD taraması (`_scan_ui_strings.py`): 30 sayfada gömülü TR UI metni = 0 (tek işaret `smmm-onay`'da doküman yorumu — muaf). Kapı: tsc ✅ vitest 95/95.

**DoD (her grup):** sayfada `[çÇğĞıİöÖşŞüÜ]` ile eşleşen gömülü UI metni kalmaz (fixture/CSV örnek verisi ve yorum hariç — `// i18n-exempt` gerekçesiyle). TR org'da TR, EN org'da EN; ilk render'da yanlış dil flash'ı yok. `npx tsc`, `next lint`, vitest yeşil.

### 1.2 Rol dashboard'ları: şema sözleşmesi
CHRO'da düzeltildi sınıfı (UI ↔ backend anahtar uyumsuzluğu) tüm rol sayfalarında sözleşme altına alınır.

- [x] Her rol sayfası için `lib/<role>-result.ts` normalizer'ı (varsa) ve **"backend ne dönerse o" testi**: gerçek API yanıt fixture'ı (kayıttan alınmış) — `undefined`/`String(undefined)`/`NaN` basamaz. Kapsam: **cto ✅ cmo ✅ coo ✅** (`aed6355` + `7c42e77`: wire fixture + NaN/bozuk-veri/boş-durum testleri; cast'ler tek normalize noktasına indi; union'lar dürüst `string`'e açıldı) + **ceo ✅ risk ✅ audit ✅** (bu sprint: `ceo-result.ts` — cross_risks `title→description`/`domains[0]→domain` alias'ı, JSX `as CEOResult & {}` cast'leri kalktı, ölü `SAMPLE_BOARD_DECK`/`SAMPLE_OKRS` (kullanılmayan uydurma metrikler + `$`) temizlendi; `audit-result.ts` — `any` findings/controls/coverage yerine tipli satırlar; `risk-report.ts` — üç API girişinde tek normalizer, `kri_posture`/`kri_value` nullable, bilinmeyen posture → `no_data`, bilinmeyen KRI status → `amber` (asla sakin yeşil), counts wire kırıksa `all_kris`'ten türetilir).
- [ ] Para her yerde `useCurrencyFormat` + org locale/currency; `₺`-hardcode ve USD-default kalmaz (frontend tarafı Grup A–D'de büyük ölçüde bitti; kalan tarama bu maddede).
- [x] **Casing + gömülü TR grep kapısı:** `frontend/src/__tests__/casing-gate.test.ts` — (1) tüm `(dashboard)` sayfalarında yorum/template/regex muafiyetli düz TR karakter taraması (gömülü kopya = 0; sample CSV blokları ve TR eşleyen regex'ler veri sayılır, muaf), (2) sayfa kopyası + `tr.ts` üzerinde `I`+sesli harf (yanlış İ-casing) = 0. Rozet `text-transform` düzeltmeleri önceki sprint'te yapıldı (`87cd317`, `335991e`, `712c027`) + canlı tarama doğrulandı. Bu kapı: `analytics` + `command-center` sayfaları i18n'e bağlandı (useI18n yoktu — 30+ satır TR copy → `analytics`/`commandCenter` message key'leri, `relativeTime` locale-parametreli), 1.2 ile birlikte kapandı.

**DoD:** `frontend/src/__tests__/` altında her rol için normalizer/fixture testi; canlı kontrolde 6 rol sayfasında `undefined`/`NaN` basan kart yok; casing kapısı yeşil.

### 1.3 Kanıt/ provenance bileşeni
- [x] Gerçek · Tahmin · Benchmark ayrımı tek ortak bileşenle (DESIGN.md kuralı) metric kartına iliştirilir; `pnl`, `tax`, `analytics`, `budget` öncelikli. (2026-10-15: `ProvenanceBadge` (`components/ui/provenance-badge.tsx`) tek nokta — `classifyDataSource` backend `platform/provenance.py` SYNTHETIC_SOURCES'ı aynalar (real/manual/rule_based → Gerçek, estimated/derived → Tahmin, benchmark → Benchmark; **tanınmayan/eksik değer → rozet yok** — sakin "Gerçek" uydurulmaz), i18n tr/en etiket + erişilebilir `title` açıklaması (wire `basis` metni ekiyle). Backend: `GET /dashboard/{job_id}` okuma-anında `provenance` haritası damgalar (`SECTION_PROVENANCE`: pnl/kpis/cashflow/multi_period/transactions→real, tax→rule_based, budget→manual, forecast→estimated) — depolanmış raporlar (golden replay dahil) göç olmadan etiketlenir; `_BASIS`'e `manual` eklendi. Ekim: pnl KPI strip + BenchmarkPanel başlığı, tax KPI strip, budget summary, analytics makro kartı (tcmb_api/redis_cache→Gerçek, static_fallback→Benchmark, bilinmeyen→yok) + benchmark kartı. Kapı: `test_dashboard_provenance.py` (wire'da 4 sınıf + basis dolu) + `provenance-badge.test.tsx` (sınıflandırıcı matrisi + render/hiç-render); canlı: konuk dashboard'unda tam harita doğrulandı.)

### 1.4 Para birimi dürüst süpürmesi (U1) — ✅ (2026-10-14)
- [x] **33 `$` sitesi sınıflandırılıp ₺'ye çevrildi** (inline ₺ swap — her sitenin sayı formatı korundu; `pnl/cashflow/forecast/chat/infra/synthesis/strategic_priorities/loss/campaign/resource/budget` + **exporter Excel/CSV başlıkları** (`Amount (₺)`, `Cash In (₺)`) + **chat LLM promptu** (`Format currency as ₺X,XXX`) + yorumlar/loglar (`risk/orchestrator` dahil).
- [x] **Ek dürüstlük bulguları (süpürme sırasında):**
  - `chat_agent.fmt` kuruşu **bölmeden** basıyordu → CFO chat LLM bağlamı 100× şişirilmiş tutar üretiyordu (ör. ₺45,900 yerine "₺4,590,000") → `₺{cents / 100}` ile fix.
  - `infra_agent` logger `%,.0f` geçersiz spec — log formatting error (latent) → `₺%s` + f-string ile onarıldı.
- [x] **Kapı testi:** `backend/tests/test_honesty_currency.py` — `app/` genelinde `$`+rakam/`${` deseni yalnız belgeli allowlist'te geçer: `model_gateway`/`services/llm_router` (LLM harcaması gerçekten USD), `stream`/`ws_alerts` (gömülü JS template), `financial.format_currency_usd`, asyncpg `$n` placeholder satırları.
- Not: Çoklu para birimi sembol tablosu/org-seçimi bilinçli olarak kapsam dışı (bkz. Kapsam dışı); TR varsayılanı ₺.

### 1.5 Hydration & yükleme UX'i (U2/S1) — **yeni**
- [x] Context yüklenirken **skeleton / "Son analiz yükleniyor"** göstergesi; form ve sonuç aynı anda yarışmaz (form, hydrasyon kararına göre gecikmeden açılır). (2026-10-14: `HydrationHint` — `role="status"`, `t.empty.hydration` tr/en — 5 rol sayfasında (ceo/cto/cmo/coo/chro); `hydrating` state hydrasyon effect'inde `finally` ile kapanır, sonuç zaten varken hint görünmez, form hiçbir sayfada hint'e bağlı değil. Kapı: `hydration-hint.test.tsx` — bekleyen fetch'te hint + form ikisi birden görünür, settle olunca hint düşer.)
- [x] `company_context` Redis okumasında **2sn timeout** → hemen DB fallback (Redis kesintisi 15-20sn'ye değil ~2sn'ye düşer). (2026-10-14: `socket_timeout=2` + `asyncio.wait_for` — DNS çözümlemesi dahil her adım sınırlı; başarısız connect'e 30sn cooldown → ceza istek başına değil pencere başına; test `test_company_context_timeout.py` — asılı okuma/init <4sn'de DB fallback'e düşer.)
- [x] İpucu: `refetchIntervalInBackground` ile zombi polling kapanır. (2026-10-14: `useAgentJobStatus`'taki `refetchIntervalInBackground: true` kaldırıldı — takılan bir job gizli sekmede sonsuza dek 2sn'de bir istek yakıyordu; sekre gizliyken polling react-query varsayılanıyla durur, odak dönüşünde `refetchOnWindowFocus` (açık) + `staleTime: 0` anında tazeler. Uzun soluklu diğer poller — context 60s / notifications 20-30s / conflicts / system-ops — arka plan polling'ini zaten kapalı tutuyor.)

**DoD:** Redis yokken sayfa açılıştan ≤3sn'de karar verir; form→sonuç yutması canlıda tekrarlanmaz.

### 1.6 Rol sayfaları doldurma & micro-fix'ler (U5/U6/U8) — **yeni**
- [x] **COO:** örnek SLA/süreç/kaynak CSV'lerle (CHRO'daki PH gibi) canlı popülasyon + 1.2 fixture'ı. (2026-10-14: `SAMPLE_PROCESSES`/`SAMPLE_SLA` zaten IS_DEMO `sampleData` olarak bağlı — CHRO'nun PH deseniyle aynı; formda "kaynak" adlı üçüncü bir input yok, kapsam 2 CSV. 1.2 fixture'ı `coo-normalizer.test.ts` ✓; canlı doğrulama: scan /coo context'ten dolu, 1616 karakter temiz.)
- [x] **CEO:** girdi yokken ana buton yönlendirici mesaj versin (400 değil); auto-chain skip'i görünür log/not olarak yazsın. (2026-10-14: `activeCFOJobId` yokken submit `disabled` + `noCfoInputHint` yönlendirici notu (tr/en) — mahkum istek hiç gitmiyor; `POST /ceo/analyze`'in "en az bir girdi" 400'ü (api/ceo.py:97) böylece tetiklenmez. auto_chain: üç skip kararı (conductor rol atlaması ×2 + eksik veri) `debug`→`info` — üretim log'unda zincirin nerede durduğu görünür. Kapı: `demo-samples.test.tsx` "CEO no-input guard" (buton disabled + not görünür).)
- [x] **Health skoru:** kartta "bileşenler kendi ölçeklerinde, genel skor ağırlıklı" açıklaması (10.0 vs 7.0 karışıklığı). (2026-10-14: `scoreScaleNote` (tr/en) İK sağlık kartının skor ızgarasının hemen altında; parite testi korur.)

**Faz 1 çıkış kapısı:** ✅ GEÇTİ (2026-10-15)
```powershell
python scripts/verify.py          # --fast YOK: mypy da dahil  → ✓ ALL CHECKS PASSED (6 checks)
cd frontend; npx tsc --noEmit; npx next lint; npx vitest run  →  0 / 0 / 154-154
# + canlı dürüstlük taraması: 6 rol sayfasında undefined/NaN/$/İ-casing = 0  → scan 10/10 temiz
```
Kanıt: `verify.py` tek koşuda 6/6 (`db45fb8` öncesi); vitest 154/154 (1.3 rozet testleri dahil); `scan_demo_pages.py` 10/10 (1.3 ekimlerinden sonra). 1.4–1.6 + 1.3 tamam → **Faz 1 kapandı.** Sıradaki: **DEMO D3 (2.6) → Faz 2 → D5/D6 (3.6–3.7) → Faz 3** + Bakım sprinti.

---

## §V4 — Öncelik sırası (2026-10-21)

**Kural:** önce sessiz yanlışlar (kullanıcıya "çalışıyor" görünüp çalışmayan şeyler), sonra yeni yetenek. Her madde ayrı commit + kendi DoD'u; commit yalnız `verify.py` exit 0 iken.

| Sıra | İş | Boyut |
|---|---|---|
| **V0** | Plan hijyeni + branch birleştirme kararı | yarım gün |
| **V1** | P4 tetik motorunu kapat (eksik olay kaynakları + canlı uçtan uca) | 1–2 gün |
| **V2** | Dürüstlük düzeltmeleri (stres kartı EUR, i18n, kapı kapsamı) | 1 gün |
| **2.6 → 2.3 → 2.2 → 2.1 → 2.5** | Faz 2 gerçek boşlukları (aşağıda "Kodda durum" notlarıyla) | 1–2 hafta |
| **3.1 → 3.3 → 3.2 → 3.5** | Faz 3 production kanıtı | 1–2 hafta |
| **3.6 → 3.7** + Bakım | Demo D5/D6, next 16, kalite denetimi, sahip kararları | — |

### V0 — Plan hijyeni
- [x] v3+v4 plan düzenlemelerini commit'le (`DEVELOPMENT_PLAN.md`, `DEMO_PLAN.md`). (`58fb661`)
- [x] `backend/scripts/_*.py` geçici tarama scriptleri: kalıcı olanları adlandırıp commit'le, kalanını sil (bugün untracked). (`9c5c15e`: 8 scriptin hepsi tek seferlikti — ham SQL, sabit org/DB yolu — repodan çıkarıldı; `_` öneki artık gitignore'da "yalnız yerel prob" kuralı.)
- [x] `feat/edefter-tahakkuk` (master'ın 38 commit önünde) için karar: tek PR mı, tema bazlı bölünmüş PR'lar mı (e-Defter / i18n+UX / demo / triggers). **Sahip kararı (2026-10-21):** önce V1 bu branch'te, sonra PR #4 başlık/açıklama güncellenip tek PR olarak birleşir (force-push yok, ateşlenmeyen tetik master'a girmez).

**DoD:** `git status` temiz; branch için PR açık ya da bölme planı yazılı.

### V1 — P4 tetik motorunu kapat
- [x] `anomaly.detected` kaynağı: `sources.emit_anomaly_detected` — kalıcı `Anomaly` satırlarından okur; analiz (worker + onay devamı `emit_job_events` üzerinden), günlük tarama (`scheduler._scan_recent_jobs`) ve elle tarama (`POST /anomalies/scan`) aynı yolu kullanır. `event_ref` = `anomaly:{job}:{bulgu parmak izi}` — anomali id yerine bulgu kümesi: yeniden tarama yeni id üretir, aynı bulgular yinelenen sayılır, yeni bulgu yeni olaydır. Payload: `anomaly_count` + `by_severity`.
- [x] `schedule` kaynağı: `sources.emit_schedule_tick` + APScheduler `trigger_schedule_tick` (saatlik, `_exclusive`). Tanımda zamanlama alanı yok → semantik **günde bir kez (UTC)**; `event_ref` = `schedule:{tarih}` — günün ilk tiki ateşler, gece yarısı kapalı sunucu o günü sonraki tikte yine değerlendirir; bir org'un hatası diğerlerini durdurmaz.
- [x] ~~Alternatif~~ gerekmedi — iki kaynak da bağlandı. Ek: `/tetikler` UI ham anahtar yerine etiket + açıklama gösteriyor ("Günlük kontrol — günde bir kez (UTC)"), tr/en.
- [x] Kapı testi: `test_every_event_kind_has_an_emitter` (kontrat ↔ `sources.py` paritesi) + `test_scheduler_registers_the_schedule_tick` (emitter'ın kapısı var). `test_trigger_sources.py` 11 → 22 test.
- [x] Canlı uçtan uca (2026-10-21, SQLite dev backend): konuk org → `POST /tetikler` (`anomaly.detected`+`schedule`) → `POST /anomalies/scan` → run `fired` + `alert_id`; aynı bulgularla ikinci tarama yeni run üretmedi; scheduler tiki 2/2 ateşledi, aynı gün ikinci tik 0 → `/tetikler/runs`'ta `schedule:2026-10-21 fired`. (API ile; tarayıcıdan UI tıklaması yapılmadı.)

**DoD:** `pytest tests/ -q -k trigger` yeşil + parite testi + canlı koşu kanıtı (tetik id, run status `fired`). → ✅ **V1 kapandı (2026-10-21):** `verify.py` 6/6 (3612 passed, vitest 166/166) + canlı kanıt yukarıda.

### V2 — Dürüstlük düzeltmeleri
- [x] `MacroStressTestCard`: `eur_shock_pct` kendi değerini alsın (ayrı EUR slider ya da açıkça "USD+EUR birlikte" etiketi — sessiz kopya yok); kartın TR metinleri message tree'ye; sonuç kartına `ProvenanceBadge` (`tcmb_api`/`redis_cache` → Gerçek, `static_fallback` → Benchmark, simülasyon çıktısı → Tahmin). (2026-10-22: ayrı EUR slider; `macroStress` namespace tr/en; TCMB rozeti + sonuç "Tahmin" rozeti + varsayım satırı; risk/öneri backend'den **kod** olarak gelir, metni UI'da. Ek bulgular aynı işte kapatıldı: kart command-center'da **token'sız** mount ediliyordu → her istek 401, kart hep "—" (artık `apiClient`); kurlar org para birimiyle 0 ondalığa yuvarlanıyordu (34,12 → "₺34") → TRY 2 ondalık; sürgü sırasında geç gelen eski yanıt yenisini eziyordu → istek sırası.)
- [x] `/macro/simulate` saf fonksiyonu için birim testi (kur şoku → runway/borç maliyeti yönü ve büyüklüğü). (`app/services/macro_stress.py` + `test_macro_stress.py` 10 test. Uçtaki üç dürüstlük hatası düzeltildi: dashboard `pnl` **lira dönem toplamı** kuruş-aylık sanılıyordu → lira çıktıları 100× küçük ve "aylık" gider tüm dönemin; CFO analizi yokken **uydurma şirket** (runway 12, gider ₺100k, gelir ₺150k) kullanıcınınmış gibi gösteriliyordu → artık `simulation_result: null` + `baseline_missing_reason`; kârlı tahminde (`runway_months: None`) 12 ay runway uyduruluyordu → "sınır yok" + şok nakit akışını negatife çeviriyor mu. Uydurmayı kilitleyen eski `test_simulate_macro_shock` yeniden yazıldı. Canlı kontrolde bir tane daha: kalıcı dashboard `pnl`'i `total_opex` değil kategori bazlı `opex` taşıyor → eski uç **her gerçek org için** uydurma ₺100k gidere düşüyordu; artık kategori toplamı okunuyor. Canlı (konuk org): runway "Sınır yok", Düşük risk, +₺21.188/ay, "Tahmin" rozeti, 12 aylık veri.)
- [x] `casing-gate.test.ts` kapsamı `components/**` (+ `components/demo/**`). Genişletince **50 bileşende 644 satır** gömülü TR çıktı — tek commit'lik iş değil, göç. Karar: mypy allowlist gibi **ratchet** — `casing-gate.baseline.json` dosya başı sayıları sabitler; sayı yalnız düşer (düşünce baseline da düşürülmek zorunda), listede olmayan bileşen 0 olmalı, `components/demo/**` + `components/macro/**` asla baseline'a giremez. Demo bileşenleri bu işte temizlendi (`demo` namespace); `QuickDemoBanner`'ın "6 Finansal Anomali" iddiası yanlıştı (demo verisi 4 üretir) → sayı kaldırıldı. **Yakalanan regresyon:** `GuestDemoButton`'a i18n eklemek login/landing'de `useOrgSettings` → oturumsuz `/org/me` 401 → apiClient signOut + login'e yönlendirme → **sonsuz yeniden yükleme** üretti (canlı tarayıcıda görüldü, commit'lenmeden). Kök düzeltme: `useOrgSettings` yalnız `status === "authenticated"` iken çeker; `org-settings-gate.test.tsx` kilitler. Canlı: login'de `/org/me` = 0, konuk girişi `/upload`'a iniyor.

**DoD:** vitest + casing kapısı yeşil (genişletilmiş kapsamla); stres kartı EUR ≠ USD girdisinde farklı sonuç verir (test). → ✅ **V2 kapandı (2026-10-22).**

### V2b — Bileşen i18n göçü (ratchet'i sıfıra indir)
- [ ] `casing-gate.baseline.json`'daki 644 satır / 50 bileşen message tree'ye taşınır; en büyükler önce: `decision-packet-panel`, `evidence-chain-panel`, `agent-chat-panel`, `PricingTable`, `cross-agent-intelligence`. `landing/**` (ziyaretçi yüzü) ve `ui/product-tour.tsx` 2.6 ile birlikte.
- Her dosya taşındıkça baseline düşürülür (`CASING_BASELINE_UPDATE=1 npx vitest run casing-gate`); hedef baseline = `{}`.

---

## FAZ 2 (Sprint 2, Hafta 3–4) — "Moat ve karar döngüsü"

**Tema:** Türkiye'ye özgü derinlik + kanıtlanmış sayısal cevap + çatışma → karar + demo hikâyesi.
**Önerilen sıra (v4):** 2.6 (tur — bileşen var, uyarlama) → 2.3 (consensus — büyük ölçüde var, canlı doğrulama) → 2.2 (grounding — gerçekten açık) → 2.1 (stres — V2 düzeltmelerinden sonra kalan) → 2.5 (SMMM — en büyük). 2.4 kodda var.

### 2.1 TCMB EVDS → canlı stres testi
> **Kodda durum (2026-10-21):** `components/macro/MacroStressTestCard.tsx` (USD/faiz/ödeme gecikmesi slider'ları → `POST /macro/simulate`) `command-center`'da mount'lu. Hatalar V2'de: EUR=USD, gömülü TR, kaynak etiketi yok. V2 sonrası kalan: widget'ın `analytics`'e de taşınması + EVDS anahtarsız fallback'in canlı doğrulaması.
- [ ] `tcmb_macro` snapshot'ından **Kur/Faiz şok simülatörü**: slider → nakit akışı/FAVÖK etkisi anında.
- [ ] Zorunlu kaynak etiketi (`tcmb_api` / `redis_cache` / `static_fallback`) + "Tahmin" etiketi; fallback asla canlı gibi sunulmaz.
- [ ] Widget `analytics`; TR/EN metin message tree'de.

**DoD:** `EVDS_API_KEY` yokken sayfa çalışır ve "statik fallback" etiketiyle çizilir; şok senaryosu pure-fonksiyon testi yeşil.

### 2.2 Grounding: citation zorunluluğu
> **Kodda durum:** gerçekten açık. `test_semantic_api_contract.py::test_chat_agent_runway_grounded` tek bir runway iddiasını kapsıyor; genel "her sayısal iddia → `EvidenceBundle`" zorunluluğu ve CI hard-fail yok.
- [ ] Embedding yazımı worker'da zorunlu; yükleme sonrası boşsa job `awaitingReview` + log.
- [ ] `/chat/agent` yanıtındaki her sayısal iddia `EvidenceBundle`'a bağlı; bağlanamayan iddia için hard disclaimer.
- [ ] Eval halüsinasyon case'i > 0 → **CI hard-fail** (`eval-grounding.sh` → `verify.py`).

**DoD:** `pytest tests/test_agents/test_grounding_eval.py test_chat_grounding.py -q` yeşil + "citation yoksa uydurma" case'i.

### 2.3 Çatışma → konsensüs → CEO kararı
> **Kodda durum:** üç madde de kodda — doğrulanmamış. Kalan iş = DoD'un kanıtı (zıt sinyalli fixture testi + canlı koşu) ve çıkan hataların onarımı.
- [~] CFO+risk tamamlanınca otomatik `run_consensus` (mevcut `ConsensusEngine`). (`auto_chain._run_auto_consensus` — non-fatal; sessiz yutulan hata olup olmadığı kontrol edilecek.)
- [~] Command Center **Conflict Card**: severity, çelişen agent'lar, önerilen konsensüs, tek tıkla karara bağlama. (`components/command-center/ConflictCard.tsx` mount'lu.)
- [~] `GET /system/ops` → `management.conflicts` sayacı. (`api/system.py`: `open_conflicts` / `recent_conflicts`.)

**DoD:** Zıt sinyalli fixture'da kart render; resolve sonrası açık çatışma yok. Canlı: `scripts/tr-governance-e2e.sh`.

### 2.4 Semantic spine API kontrat testleri
> **Kodda durum:** `backend/tests/test_semantic_api_contract.py` var (rebuild+read, grounded runway). Kalan: `/negotiation/conflicts/{org}` ORM listesi assertion'ının kapsamda olduğunu doğrula; yoksa ekle.
- [~] `POST /semantic/me/rebuild` → 200 + metrics > 0; `GET /semantic/me` → `snapshot.period.key`; `GET /semantic/me/brief` → runway+conflict; `GET /negotiation/conflicts/{org}` ORM listesi.

### 2.5 SMMM mühürlü export paketi (moat)
> **Kodda durum:** temel var — `DefensibilityPacket` (SHA-256 mühür, finalize, PDF export, `smmm-defensibility-smoke.sh`). Kalan iş bu paketi **genişletmek** (KDV/stopaj kontrolü, anomaliler, e-Defter berat özeti, Excel); yeni silo açılmaz.
- [ ] Tek tıkla resmi paket: yevmiye dökümü, KDV/stopaj kontrolü, anomaliler, e-Defter berat uyumluluk özeti → PDF + Excel.
- [ ] İmza/metaveri: şirket, dönem, üretim zamanı (UTC), veri kaynakları, "agent üretti, SMMM onayladı" mühür alanı. Otomatik onay yok.

### 2.6 Demo turu (DEMO_PLAN D3) — ÖNCELİK 2
> **Kodda durum:** `components/ui/product-tour.tsx` (358 satır, popover adımları) yalnız `/upload`'da kullanılıyor; metinler TR sabit. Yeni bileşen yazılmaz — bu bileşen 4 demo adımına + message tree'ye uyarlanır.
- [ ] 4 adım: (1) CFO özeti & runway, (2) anomali denetimi, (3) CEO brief / çapraz risk, (4) "Şirketinizle deneyin" CTA. Step JSON i18n'de (tr/en) — `driver.js` yok, mevcut ui ile basit step-panel.
- [ ] İlk girişte otomatik başlangıç; sidebar'da "Turu tekrarla".
- [ ] auto-chain görünürlüğü (1.6 ile birlikte): demo izleyicisi ajanların çalıştığını görür.
- [ ] `components/demo/**` `casing-gate.test.ts` tarama kapsamına eklenir (DEMO_PLAN §4 kırmızı çizgisi).

**DoD:** tur tr/en parite testi + `scan_demo_pages.py` yeşil; tur sonunda CTA görünür.

**Faz 2 çıkış kapısı:**
```powershell
python scripts/verify.py
./scripts/tr-governance-e2e.sh
./scripts/smmm-defensibility-smoke.sh
python scripts/scan_demo_pages.py   # demo sayfaları hâlâ dürüst + tour erişilebilir
```

---

## FAZ 3 (Sprint 3, Hafta 5–6) — "Production kanıtı"

**Tema:** Tarayıcı seviyesinde uçtan uca kanıt + çoklu pod + sertifikasyon kapıları.

### 3.1 Playwright Golden Path (yeni: `frontend/e2e/`)
1. Login → org seçimi  2. `baglan`/`upload` → CSV → kolon eşleştirme → analiz  3. SSE canlı ilerleme  4. CFO/CEO kartları (`undefined`/`NaN` taraması)  5. Chat → yanıt → kanıt rozeti  6. SMMM onay kuyruğu
- [ ] `npm run e2e` CI'da koşar; yeşil PR kırmazsa sprint kırmızı.
- [ ] `scripts/golden-path-e2e.sh` bu paketi çağırır.

### 3.2 SSE Redis Pub/Sub (multi-pod)
> **Kodda durum:** `streaming/sse.py` zaten `sse:job:{job_id}` Redis pub/sub köprüsü (worker yayınlar, API teslim eder). Kalan: iki process arası yayın testi (bu makinede Redis yok → CI'da ya da Docker kararından sonra).
- [~] `streaming/sse.py`: bellek yerine Redis kanalı ✅; iki pod arası event yayını testi ❌.

### 3.3 Tenant izolasyonu denetimi (IDOR/BOLA)
> **Kodda durum:** rota düzeyi kapandı (2026-09-13: `app/api/access.py` + `tests/test_route_access.py` her rotayı yürüyor). Kalan: tablo düzeyi tarama + field encryption kanıtı.
- [~] `org_id`'li tüm tablolarda otomatik tenant filtresi taraması; negatif test paketi: org B → org A job'ı 404/403. (Rota paketi ✅; tablo taraması ❌.)
- [ ] Hassas kolonlarda (VKN, IBAN, API key) field encryption kanıtı: DB'de şifreli, bellekte net.

### 3.4 Güvenlik & config sertleştirme
> **Kodda durum:** ilk iki madde kodda — `config.py` `_INSECURE_SECRETS` kontrolü, `middleware/security_headers.py` (HSTS, CSP, …) + `test_agents/test_perf_security.py`. Kalan: prod modunda exception'ın testle kilitli olduğunu doğrula; ARQ ayrım testi.
- [~] Prod'da insecure `BACKEND_SECRET_KEY` default → exception (testte kalır).
- [x] Security headers (CSP, HSTS, X-Content-Type-Options, X-Frame-Options) + test.
- [ ] ARQ analysis/maintenance ayrımının uygulandığını gösteren test (yeni queue mimarisi yok).

### 3.5 Yük & gözlemlenebilirlik
- [ ] `./scripts/load-baseline.sh` CI artifact'i; P95: upload→analiz başlangıcı, board deck < 120s.
- [ ] `/system/ops`: LLM maliyeti, failed job oranı, awaiting-review yükü.

### 3.6 Public demo ortamı (DEMO_PLAN D5) — ÖNCELİK 3
- [ ] Ayrı deploy (compose tabanlı): `NEXT_PUBLIC_DEMO_MODE=true`, kendi DB volume, seed'li görüntü (golden prefill).
- [ ] Otel: günlük otomatik `prefill` tazeleme, log/metrics, LLM maliyet cap'i (default kapalı).
- [ ] Demo → gerçek geçiş: kayıt olunca gerçek org açılır, demo org bağlanmaz (veri izolasyonu).

### 3.7 CTA & ölçüm (DEMO_PLAN D6) — ÖNCELİK 3
- [ ] Tour sonu + banner CTA: mail capture + pricing; `POST /demo/lead`.
- [ ] Basit sayaçlar: demo başlattı / tur tamamladı / CTA tıkladı (privacy-hostile değil).

**Faz 3 çıkış kapısı (release adayı):**
```powershell
python scripts/verify.py
cd frontend; npm run e2e
./scripts/golden-path-e2e.sh
BACKEND_URL=http://localhost:8000 ./scripts/staging-smoke.sh
docker compose -f docker-compose.demo.yml up -d   # + scan_demo_pages.py → 10/10 temiz
```

---

## Sahip kararları (açık — 2026-09 hafızasından, kodda yeniden doğrulanmalı)

Bunlar teknik değil ürün/güvenlik kararı; her biri önce kodda hâlâ geçerli mi diye kontrol edilir, sonra sahibe sorulur (CLAUDE.md DISPATCH).

- [ ] **`/efatura/sync` uydurma GİB API'si** (`/login`, `/earsiv/documents`) + platform-geneli tek kimlik bilgisi + sahipsiz job → kaldır mı, gerçek entegratör (özel entegratör API'si) mi?
- [ ] **`classify()` (kullanıcı düzeltme kuralları) hiçbir yerden çağrılmıyor** → düzeltmeler sonraki analizlere uygulanmıyor. Bağla mı, kaldır mı?
- [ ] **Legacy X-API-Key düz metin kabul ediyor** → auth değişikliği (DISPATCH).
- [ ] **`audit_log`'da `org_id` ve retention yok** → tenant izolasyonu + saklama politikası.
- [ ] **Docker/Postgres/Redis yok** (2026-08-31 kararı) → worker yolu, iki-pod SSE, Paraşüt ve e-posta sağlayıcısı doğrulanamıyor. Faz 3 kanıtı için yeniden değerlendir.

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
| Faz 2 tek sprint'e sığmaz (6 madde) | Sıra (v4): 2.6 → 2.3 → 2.2 → 2.1 → 2.5; her madde ayrı commit + kendi DoD'su; 2.5 tek başına sprint olabilir |
| Plan yine koddan kopar (v3'te oldu: P4 plan dışı yapıldı, var olan maddeler "başlamadı" yazıldı) | Plan dışı iş başlamadan önce §V4'e satır eklenir; her faz başında "Kodda durum" notları grep ile tazelenir |
| Playwright CI'da flaky | İlk sprint sadece golden path, retry 0, locator bekleme |
| EVDS API anahtarı / erişim yok | 3 katmanlı fallback + kaynak etiketi zorunlu |
| pgvector yoksa embedding'ler boş | Nullable kalır; boş kalınca job → `awaitingReview` |

## Günlük ritim

```powershell
# her gün, yeni işe başmadan
python scripts/verify.py --fast --backend
cd frontend; npx vitest run
```

- Backend dev sunucusu `--reload` + sabit `.env` secret ile (Hemen maddesi) — restart'ta oturum kopmaz.
- Yeşil değilse sprint kırmızıdır. Yeni UI, kanıtlanmış eski UI'dan önce ilerleme değildir.
