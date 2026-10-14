> ⚠️ **Bu dosya artık tarihsel kayıt.** Güncel ve tek geçerli plan: [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) (2026-10-11).

# 🏛️ Master Geliştirme, Güvenlik ve Performans Planı — Agentic CFO

> **Hedef:** Mevcut 3.400+ testlik güçlü temeli; kurumsal seviyede siber güvenlik, dağıtık performans/lock yönetimi, derinleştirilmiş C-Suite zekası ve Türkiye muhasebe moatı ile donatılmış, production-ready bir SaaS platformuna dönüştürmek.  
> **Temel Kanun:** `CLAUDE.md` — Done = `python scripts/verify.py` exit 0, Confidence Gate ≥ 0.80, Verifier bağımsızlığı, Tamsayı kuruş/cent standardı.

---

## 🧭 Planın 5 Temel Sütunu

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    AGENTIC CFO ENTERPRISE MASTER PLAN                        │
├──────────────────────┬──────────────────────┬────────────────────────────────┤
│ 1. MEVCUT GÜÇLENDİRME│ 2. YENİ ÖZELLİKLER   │ 3. PERFORMANS & LOCK           │
│  - RAG v2 Grounding  │  - Playwright E2E    │  - Redlock / Job Lease         │
│  - Multi-agent Hub   │  - TCMB Live Feed    │  - Queue Separation (ARQ)      │
│  - Semantic Spine    │  - C-Suite War Room  │  - DB Pool & Deadlock Guard    │
├──────────────────────┴──────────────────────┼────────────────────────────────┤
│ 4. SİBER GÜVENLİK & VERİ KORUMA (KVKK/GDPR)  │ 5. FAZLANDIRILMIŞ YOL HARİTASI │
│  - Multi-tenant Row-Level Boundary          │  - Faz 1: Güvenlik & Lock      │
│  - AES-256-GCM Sütun Şifreleme (IBAN/VKN)   │  - Faz 2: RAG & Semantic Spine │
│  - XXE & Ingestion Zırhı                    │  - Faz 3: E2E & Frontend       │
│  - Değiştirilemez Kriptografik Audit Trail  │  - Faz 4: TR Moat & War Room   │
└─────────────────────────────────────────────┴────────────────────────────────┘
```

---

## 1. 🛡️ Siber Güvenlik ve Veri Güvenliği (Enterprise Security)

Finansal veriler (e-Fatura, banka ekstreleri, çalışan bordroları, P&L) en yüksek seviyede regülasyon ve saldırı riskine tabidir.

### 1.1 Multi-Tenant İzolasyon & Zorunlu Org Sınırı (Tenant Leakage Prevention)
* **Risk:** Bir organizasyonun kullanıcısının başka bir şirketin faturalarını veya CFO analizini görmesi (IDOR / BOLA açığı).
* **Çözüm:**
  - SQLAlchemy AsyncSession seviyesinde **Otomatik Tenant Filter (RLS pattern)**: `org_id` kolonu olan tüm tablolarda `current_tenant_id` context variable'ı zorunlu filtre haline getirilecek.
  - API katmanında `assert_owns_org` ve `assert_owns_job` yetki matrisinin tüm endpoint'lerde decorator/dependency olarak standartlaştırılması.

### 1.2 Hassas Verilerin Şifrelenmesi (Field-Level Encryption / AES-256-GCM)
* **Risk:** Veritabanı yedeğinin ele geçirilmesi durumunda VKN (Vergi Kimlik No), IBAN, müşteri ticari unvanları ve banka hesap bakiyelerinin ifşa olması.
* **Çözüm:**
  - `app/core/crypto.py`: SQLAlchemy `TypeDecorator` kullanarak `EncryptedString` tipi oluşturulacak.
  - Hassas kolonlar (VKN, IBAN, banka hesap no, API key'ler, erişim tokenları) veritabanına yazılırken AES-256-GCM ile şifrelenecek, sadece belleğe okunurken çözülecek.
  - Master şifreleme anahtarı çevre değişkeninden (`ENCRYPTION_KEY`) alınacak; eksikse sunucu ayağa kalkmayacak.

### 1.3 XML & Doküman Güvenliği (XXE, Zip-Bomb, SSRF Koruma)
* **Risk:** e-Fatura / e-Arşiv XML dosyaları ve Excel tabloları üzerinden XXE (XML External Entity Injection), Billion Laughs saldırısı ve dosya ayrıştırma istismarları.
* **Çözüm:**
  - `app/core/xml_safety.py` mevcut zırhının güçlendirilmesi: DTD, harici entity ve XML entity referansları kesinlikle engellenecek (defusedxml / lxml entity disabled).
  - Dosya tipi kontrolü sadece uzantı ile değil `python-magic` ile **MIME-Type & Magic Byte** seviyesinde doğrulanacak.
  - Boyut sınırı katı 10 MB tutulacak; zip-bomb içeren XLSX dosyalarına karşı decompress ratio limit kontrolü konulacak.

### 1.4 Güvenlik Başlıkları, JWT & Secret Yönetimi
* **Risk:** Varsayılan anahtarlar, XSS, CSRF, Clickjacking ve yetkisiz token kullanımı.
* **Çözüm:**
  - `BACKEND_SECRET_KEY` için test/insecure uyarısı prod ortamında exception fırlatacak (`assert settings.secret_key != "insecure-default"`).
  - JWT token'ları HttpOnly, Secure, SameSite=Strict cookie içinde taşınacak.
  - Security Header Middleware: CSP (Content Security Policy), HSTS, X-Content-Type-Options: nosniff, X-Frame-Options: DENY.

### 1.5 Kriptografik Denetim İzi (Tamper-evident WORM Audit Trail)
* **Risk:** Finansal usulsüzlük durumunda geçmiş analiz veya onay kayıtlarının manipüle edilmesi.
* **Çözüm:**
  - `AuditLog` tablosuna `previous_hash` ve `hash` (SHA-256) kolonları eklenerek blokzincir benzeri zincirleme hash oluşturulacak. Kayıt silinemez veya geriye dönük değiştirilemez.

---

## 2. ⚡ Performans, Eşzamanlılık ve Lock Yönetimi (Concurrency & Scale)

Eşzamanlı yüklemelerde, birden fazla agent'ın aynı anda çalışmasında veya veritabanı kilitlenmelerinde (deadlock / race conditions) sistemin tıkanmaması gerekir.

### 2.1 Dağıtık Lock & Job Lease (Race Condition & Double-Run Önleme)
* **Sorun:** Kullanıcı aynı anda iki kez "Analiz Et" butonuna bastığında veya webhook tekrar tetiklendiğinde iki worker aynı analiz üzerinde yarış durumuna girip veriyi bozabilir.
* **Çözüm:**
  - **Redis Redlock / DB Lease Hibriti:** `job_state.py` içindeki job lease mekanizması Redis distributed lock (`asyncio` timeout destekli) ile desteklenecek.
  - Analiz başlayan job için Redis üzerinde `lock:analysis:{job_id}` anahtarı 300 saniye TTL ile kilitlenecek. İşlem bitince `release_lock` çağrılacak.

### 2.2 Veritabanı Connection Pool & Deadlock Koruması
* **Sorun:** Arka plan worker'ları (ARQ) ile API istekleri aynı connection pool'u paylaştığında connection starvation veya SQLite dev ortamında `database is locked` hatası.
* **Çözüm:**
  - Postgres Pool Optimizasyonu: `pool_size=20`, `max_overflow=10`, `pool_timeout=30`, `pool_recycle=1800`.
  - Transaction Timeouts: Uzun süren sorguların DB'yi kilitlemesini önlemek için Postgres `statement_timeout = 30000` (30 sn) ve SQLite `busy_timeout = 30000` ms ayarı.
  - Read/Write ayrımı için kritik büyük sorgularda `with db.begin():` bloklarının olabildiğince dar tutulması.

### 2.3 ARQ Kuyruk Ayrımı (Queue Separation)
* **Sorun:** Ağır bir Monte Carlo simülasyonu veya LLM agent zinciri (2 dakika) çalışırken, küçük bir bildirim veya webhook işleminin arkada beklemesi.
* **Çözüm:**
  - 2 ayrı ARQ kuyruğu:
    1. `queue_heavy`: CFO LangGraph, CEO board deck, Monte Carlo, e-Defter ingest (büyük işlemler).
    2. `queue_fast`: Webhook bildirimleri, alert routing, audit log yazımı, e-posta gönderimi.
  - Worker'lar bu kuyruklara öncelikli atanacak.

### 2.4 SSE ve Redis Pub/Sub ile Çoklu Pod (Multi-Replica) Desteği
* **Sorun:** Birden fazla sunucu/pod çalıştığında bellekteki event bus diğer pod'daki kullanıcıya SSE bildirimini ulaştıramaz.
* **Çözüm:**
  - `app/streaming/sse.py`: Yerel bellek kuyruğu yerine `Redis Pub/Sub` kanalları (`org:{org_id}:job:{job_id}`) üzerinden dağıtık event yayını.

---

## 3. 🧠 Mevcut Özellikleri Güçlendirme (Feature Hardening)

### 3.1 RAG v2 & Chat Grounding (Halüsinasyon Kilidi)
* **Mevcut Durum:** RAG tabloları var ancak pgvector embedding üretimi opsiyonel kalıyor, TF-IDF fallback'e düşüyor.
* **Güçlendirme:**
  - Indexlenen her fatura, yevmiye kaydı ve şirket metni için pgvector embeddings zorunlu hale getirilecek.
  - Chat sorgularında `grounding_validator.py`: Yanıttaki her sayısal iddia (ciro, runway, kâr) dokümandaki satır id'si ile doğrulanacak (`EvidenceBundle`).
  - Kanıt bulunamazsa sistem asla uydurmayacak: *"Yüklenen verilerde bu döneme ait net kâr verisi bulunamamıştır."* hard disclaimer'ı verilecek.

### 3.2 Semantic Spine & Auto-Chain Entegrasyonu
* **Mevcut Durum:** `CompanyContext` güncelleniyor ancak uçtan uca contract testleri eksik.
* **Güçlendirme:**
  - `POST /semantic/me/rebuild` ve `GET /semantic/me/brief` için API contract testleri.
  - Conductor planı sonucunda hangi agent'ın neden tetiklendiği şeffaf şekilde `result_metadata["conductor_plan"]` üzerinden frontend Command Center'a taşınacak.

### 3.3 Çoklu Domain Çatışma Çözümü (Conflict & Negotiation Engine)
* **Mevcut Durum:** CFO ile CMO veya CTO metrikleri çeliştiğinde arka planda çatışma tespiti var.
* **Güçlendirme:**
  - Command Center'da **Conflict Resolution Card**: Örn. *"CFO runway 3 ay diyor, CMO bütçeyi %40 artırmak istiyor. Önerilen Konsensüs: Pazarlama harcamasını kademeli aç."* tek tıkla CEO kararına bağlanabilecek.

---

## 4. 🚀 Yeni Eklenecek Stratejik Özellikler

### 4.1 Playwright E2E "Golden Path" Test Paketi
* **Neden:** Uçtan uca kullanıcı yolculuğunu tarayıcı seviyesinde garanti altına almak.
* **Kapsam:**
  1. Login & Auth akışı
  2. CSV / e-Fatura yükleme -> Doğrulama -> Analiz Başlatma
  3. SSE stream canlı ilerleme çubuğu
  4. CFO Dashboard kartlarının ve grafiklerinin render olması
  5. Soru-Cevap (Chat) akışı ve kanıt görüntüleme

### 4.2 Canlı TCMB EVDS Makro Entegrasyonu & Dinamik Stres Testi
* **Neden:** Türkiye'deki şirketlerin en büyük problemi kur ve enflasyon oynaklığı.
* **Kapsam:**
  - TCMB EVDS API'sinden günlük USD/TRY, EUR/TRY, Politika Faizi, TÜFE/ÜFE otomatik çekilmesi.
  - Dashboard'a **Makro Risk Widget'ı**: *"Dolar kuru %15 artarsa veya faizler 500 baz puan yükselirse nakit akışınız ne olur?"* dinamik slider ile anında hesaplama.

### 4.3 SMMM & Denetçi Resmi Onay Paketi (Export Moat)
* **Neden:** Mali müşavir ve bağımsız denetçilere hazır, damgalı resmi rapor sunmak.
* **Kapsam:**
  - Tek tıkla resmi **SMMM Onay Paketi**: Yevmiye dökümü, KDV/Stopaj kontrolü, e-Defter berat uyumluluk belgesi ve tespit edilen anomalilerin resmi PDF/Excel çıktısı.

### 4.4 Frontend React Hooks & Performans Temizliği
* **Neden:** Stale closure ve gereksiz re-render'ları önlemek.
* **Kapsam:**
  - `next lint` sırasında uyarı veren `chat`, `audit`, `pilot`, `useAgentStream` dosyalarındaki `react-hooks/exhaustive-deps` bağımlılık dizilerinin kusursuz optimize edilmesi.

---

## 📅 Uygulama Yol Haritası (Fazlar)

```
┌────────────────────────────────────────────────────────────────────────┐
│ FAZ 1: Siber Güvenlik & Performans Temeli (1. Sprint - 1 Hafta)         │
│  [x] Mypy & test sıfırlama (Tamamlandı)                                │
│  [ ] 1.1 Tenant Context Interceptor (RLS / Multi-tenant izolasyon)    │
│  [ ] 1.2 Redis Dağıtık Lock (Redlock) & DB Deadlock Guard              │
│  [ ] 1.3 Hassas Veri AES-256 Şifreleme (Crypto TypeDecorator)         │
│  [ ] 1.4 Frontend React Hook uyarılarının temizlenmesi                 │
├────────────────────────────────────────────────────────────────────────┤
│ FAZ 2: Semantic Spine, RAG Grounding & API Kontratları (2. Sprint)    │
│  [ ] 2.1 RAG v2 Grounding Validator & Citation Engine                  │
│  [ ] 2.2 Semantic Spine Contract Testleri (/semantic/me/rebuild)       │
│  [ ] 2.3 ARQ Çift Kuyruk (Queue Separation: heavy vs fast)            │
├────────────────────────────────────────────────────────────────────────┤
│ FAZ 3: Frontend E2E & Kullanıcı Deneyimi Zırhı (3. Sprint)             │
│  [ ] 3.1 Playwright Kurulumu & Golden Path Testi                       │
│  [ ] 3.2 SSE Redis Pub/Sub Multi-Pod Desteği                           │
│  [ ] 3.3 Command Center Çatışma / Mutabakat Kartı Entegrasyonu         │
├────────────────────────────────────────────────────────────────────────┤
│ FAZ 4: Türkiye Moat & Canlı Makro Finans (4. Sprint)                  │
│  [ ] 4.1 Canlı TCMB EVDS Entegrasyonu & Kur Şok Simülatörü            │
│  [ ] 4.2 SMMM Mühürlü Resmi Rapor Dışa Aktarım Paketi (PDF/Excel)      │
│  [ ] 4.3 Kriptografik Değiştirilemez Audit Trail (WORM)                │
└────────────────────────────────────────────────────────────────────────┘
```
