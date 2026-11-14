# Plan v11 — Mimari yol haritası: bütün bileşenler, tek omurga

*2026-11-14. Plan v10'un hedefini değiştirmez: "3 gerçek şirket pazartesi nakit cevabını 6 hafta üst üste kullansın" ürünün tek ölçütü olarak kalır ve çatışmada pilot işi kazanır. v10 **ne** yapılacağını söyler; v11 sistemin **hangi mimariye, hangi sırayla** evrileceğini ve her bileşenin o yolda nerede durduğunu söyler. Süreler tek geliştirici için kabadır; pilot bulgularıyla yeniden yazılır.*

*Not: ana klasördeki commit'siz kodda (`pilot_metrics.py`, `csuite_ledger.py`) "Plan v11 Faz 4" diye anılan bir plan depoda yoktu. Bu belge o değildir; o yorumlar bu belgeye göre güncellenir ya da kaldırılır.*

---

## 1. Bugünkü sistem

Sayılar 2026-11-14'te `origin/master` (`1e106eb`) üzerinden sayıldı.

| Katman | Bileşen | Büyüklük | Not |
|---|---|---|---|
| Giriş | `parsers/` (banka, fatura, e-Defter, muhasebe), `agents/data_ingestion.py`, `services/ingest/` | 24 + 1 + 6 dosya | `data_ingestion.py` 1.157 satır, projenin en büyük dosyası |
| Bağlayıcılar | `connectors/`, `services/connectors/`, `services/data_sync/`, `services/erp/`, `services/open_banking/` | 6 + 7 + 11 + 4 + 4 dosya | Aynı iş için **beş** yer; G17/G24 |
| Kayıt | `models/` | 40 model, 51 migration | Para: `canonical_transactions`, `open_items`, `open_item_matches`; muhasebe yevmiyesi: `reports` içinde iş başına **JSON** (`journal_store.persist_journal`) |
| Türetme | `ledger`, `company_view`, `cash_radar`, `monday_briefing`, `recurring_obligations`, `tax_calendar`, `semantic/` | ~20 dosya | Saf fonksiyonlar büyük ölçüde; görünüm imzası içerik tabanlı (E1) |
| Zeka | `agents/` (8 rol + muhasebe, denetim, uyum, risk), `platform/` (model gateway, run gate, yetki matrisi, provenance) | 92 + 9 dosya | LangGraph 0.1.19, LangChain 0.2; tek sağlayıcı (OpenAI) gateway arkasında |
| Yardımcı zeka | `agent_bus`, `agent_memory`, `agent_negotiation`, `reasoning_loop`, `reflection_agent`, `retry_with_reflection`, `capability_router`, `cascade_simulator`, `counterfactual_engine` … | ~15 dosya | Çoğunun 1–5 çağıranı var; `core/llm_client.py` ve `services/financial_rag.py` hiç çağrılmıyor |
| Sohbet/RAG | `api/chat.py`, `services/rag/`, `rag_service.py`, `chat_grounding.py`, pgvector | 854 satırlık router | Kanıt artık defterden (G9) |
| Etkiler | `notification_service`, `alert_*`, `scheduler.py` (13 iş), `worker.py` (arq), `scheduled_sync.py` | 1.103 + 1.075 + 1.023 satır | Dış etkiler (e-posta, bildirim) için tekrar koruması ve outbox yok; SMTP yoksa e-posta **sessizce** atlanır |
| API | `api/` | 83 router | İş mantığının bir kısmı router'da (`muhasebe.py` 795, `ceo.py` 674, `org.py` 635 satır); erişim `api/access.py` + rota tarayan test |
| Ön yüz | Next.js 14, `frontend/src/app` | 52 ekran, 33 API istemcisi, 18 hook, 35 test dosyası | Odak modu menüyü 8 ekrana indiriyor; i18n kısmi (G16); bazı router'ların ekranı yok (`counterfactual`, `cross_domain`, `intelligence`, `open_banking`) |
| Platform | `core/` (tenancy, crypto, xml_safety, dates), `middleware/` (audit, rate limit, güvenlik başlıkları) | 19 + 4 dosya | OpenTelemetry 3 dosyada dokunulmuş; yapılandırılmış log yok |
| Altyapı | `docker-compose`, `k8s/` (15 manifest), `k8s-overlays/managed-postgres`, `helm/`, CI (proof-gate, Postgres migration, load-baseline, backend, frontend, docker, security) | | Staging yok; worker gerçek ortamda koşmadı; geri yükleme tatbikatı yok (G18) |
| Doğrulama | `verify.py`, 142 backend test dosyası (~3.930 test), vitest 210 test, ruff, mypy ratchet, Sonar | | Canlı denemeler testlerin kaçırdığı ~23 hatayı buldu |

**Güçlü taraflar korunur:** sayıyı LLM üretmez; tek şirket defteri ve içerik kimliği; güven kapısı ve ayrı doğrulayıcı adım; `AgentRun` kaydı; kiracı yalıtımı rota testiyle zorlanıyor; e-Fatura/e-Defter gibi resmî biçimler GİB'in kendi paketlerine karşı test ediliyor.

---

## 2. Teşhis: mimarinin on bir yapısal sorunu

Her satır koddan doğrulandı; dosya yolu kanıttır.

| # | Sorun | Kanıt | Neden önemli |
|---|---|---|---|
| D1 | **İki defter.** CFO defteri `canonical_transactions`; muhasebe yevmiyesi iş başına bir JSON (`reports`, `journal_store.persist_journal`). e-Defter, mizan ve yevmiye dökümü JSON'dan okunuyor. | `services/accounting/journal_store.py:35` | Aynı para iki yerde, iki kimlikle. Mizan ile P&L'nin aynı rakamı vermesi (M3) bugün garanti değil. |
| D2 | **İnsan kararları türetilmiş tablolarda.** Mükerrer kararı defter satırında, eşleşme kararı eşleşme kaydında. | `docs/data-contracts.md` "Bilinen boşluk"; G5 | Defter yeniden kurulursa kararlar kaybolur; bu yüzden defter bugün "silinip yeniden üretilemez". |
| D3 | **Görünümler istek anında ve dağınık saklanıyor.** Radar her istekte hesaplanıyor; şirket görünümü her imza değişiminde tam CFO koşusu tetikliyor; anlık görüntüler (semantik, kurumsallaşma, radar tahmini) her biri kendi tablosunda. | `post_completion.refresh_company_view`; G11 | Maliyet ölçülmemiş; tahmin notlama (O5) gibi "o gün ne görüldü" soruları her biri için ayrı çözülüyor. |
| D4 | **Dış etkiler tekrarsız değil.** E-posta, bildirim, Slack/WhatsApp ve senkron çağrıları için gönderim anahtarı ya da outbox yok; APScheduler her süreçte çalışıyor ve tekilliği Redis kilidine bağlı. | `services/notification_service.py:235` (SMTP yoksa sessiz atlama), `scheduler._exclusive` | Pilot bülteni iki kez giderse ya da hiç gitmezse kimse bilmez. |
| D5 | **Ajan katmanı ürünün ihtiyacından geniş.** 8 rol, ~15 yardımcı zeka modülü; çoğunun tek çağıranı var; iki modül ölü. Rol ajanları defterden beslenmiyor ve güvenini ölçmüyor (G13). | Bölüm 1 tablosu | Bakım yükü ve saldırı yüzeyi; odak modu zaten bunları gizliyor. |
| D6 | **Büyük, çok sorumluluklu dosyalar.** `data_ingestion.py` 1.157, `scheduler.py` 1.103, `worker.py` 1.075, `scheduled_sync.py` 1.023, `api/chat.py` 854 satır; iş mantığı router'larda. | `find -exec wc -l` | Hata bulmak ve test yazmak pahalı; "tek beceri, tek sorumluluk" ilkesine aykırı. |
| D7 | **Bağlayıcı kodu beş yerde.** `connectors/` (yeni platform), `services/connectors/`, `services/data_sync/`, `services/erp/`, `services/open_banking/`. Platform adaptörleri finans defterine değil `canonical_eng_signals`'a yazıyor. | G24 | Paraşüt pilot yolunda; hangi yolun gerçek olduğu belirsiz. |
| D8 | **Yapay zeka katmanı ölçülmedi.** LLM'li uçtan uca koşu yok, koşu başına maliyet yok, karar kalitesi ölçülmüyor. | G10, G11, G12 | "AI CFO" anlatısının yarısının kalitesi bilinmiyor. |
| D9 | **Gözlemlenebilirlik zayıf.** İzleme (trace) yok denecek kadar az, yapılandırılmış log yok; SLO yalnız `AgentRun` üzerinden. | `grep opentelemetry` → 2 dosya | Pilotta bir hata "hangi koşu, hangi belge, hangi model" diye izlenemez. |
| D10 | **Bağımlılıklar eski.** `langgraph==0.1.19`, `langchain==0.2.17`; tek model sağlayıcısı. | `backend/requirements.txt` | Güvenlik yamaları ve yeni modeller bu sürümlere gelmez; yükseltme ertelendikçe pahalanır. |
| D11 | **Ortam yok.** Staging, gerçek worker koşusu, geri yükleme tatbikatı, KVKK gözden geçirmesi yok. | G18, G19 | Pilotun önündeki engel kod değil ortam ve karar. |

---

## 3. Hedef mimari

Sistem yedi katmandan oluşur. Her katman yalnız altındakine bağımlıdır; bu bağımlılık bir mimari testle zorlanır (§8).

```
 Sunum        Next.js ekranları  ←→  ince API router'ları (zarf: {data, error, meta})
                    │
 Etkiler      Outbox → e-posta · bildirim · e-Fatura gönderimi · dış senkron   (her etki bir anahtarla, bir kez)
                    │
 Zeka         Deterministik motor (oranlar, mutabakat, radar)  +  LLM yalnız gateway'den
              (anlatı, sınıflandırma) → doğrulayıcı adım → güven kapısı → AgentRun
                    │
 Türetme      Saf projeksiyonlar: şirket görünümü · radar · bülten · mizan · e-Defter · P&L
              (aynı girdi → aynı rakam; "o gün ne görüldü" için tek anlık görüntü deposu)
                    │
 Kayıt        ┌ Belge deposu (değişmez, içerik özetli)
 (doğruluk    ├ Karar günlüğü (eklemeli, silinmez: mükerrer, eşleşme, düzeltme, onay)
  kaynağı)    └ Tek defter: çift taraflı yevmiye satırları (hesap kodu, belge kimliği, karar referansı)
                    │
 Giriş        Tek giriş sözleşmesi: dosya · e-posta · bağlayıcı → ayrıştırıcı kaydı → normalize satır
                    │
 Platform     Kiracılık · kimlik/yetki · denetim kaydı · iş yürütücü (arq + tek zamanlayıcı) ·
              gözlemlenebilirlik (trace, log, maliyet) · yapılandırma
```

### 3.1 Değişmezler (testle zorlanır)

| # | Değişmez | Nasıl zorlanır |
|---|---|---|
| I1 | Para tek defterde durur; görünümler kendi kaynağını saklamaz. | Mimari testi: türetme modülleri `models`'e yazmaz (anlık görüntü deposu hariç). |
| I2 | Türetilmiş her şey silinip belge + karar günlüğünden yeniden üretilebilir; **kararlar dahil**. | `test_ledger_rebuild` genişler: kararlı bir şirkette defteri sil, yeniden kur, kararlar ve rakamlar aynı. |
| I3 | Her dış etki bir anahtarla bir kez olur; olmayan etki kayıt bırakır. | Outbox testleri: iki koşu bir gönderim; sağlayıcı yoksa `failed` satırı. |
| I4 | Sayıyı LLM üretmez; anlatıdaki her sayı kaynağa karşı denetlenir. | Mevcut doğrulayıcı + E3 altın kümesi (uydurma sayı 0). |
| I5 | Hesaplayan adım kendi sonucunu doğrulamaz; güven < 0,80 ya da `needs_review` sahibin kuyruğuna düşer. | `test_derived_results_gate.py` ve run gate testleri (CLAUDE.md #10). |
| I6 | Her koşu bir `AgentRun` ve `JobLog` bırakır; sessiz hata yok. | Kaos testleri (E5): worker ölümü, Redis yok, yavaş veritabanı. |
| I7 | Her rota kimlik ve kiracı denetiminden geçer. | `test_route_access.py` her rotayı tarar (var). |
| I8 | Migration'lar yalnız ekler; sütun/tablo silen migration insana gider (DISPATCH). | Migration incelemesi + Postgres migration CI işi (var). |

### 3.2 Bilinçli olarak yapılmayanlar

- **Mikroservis yok.** Tek FastAPI süreci + arq worker yeterli; ölçek sorunu ölçülmeden bölünmez.
- **Kafka / ayrı olay altyapısı yok.** Outbox ve karar günlüğü Postgres tablosudur.
- **Tam olay kaynaklama (event sourcing) yok.** Yalnız kararlar ve yevmiye eklemeli tutulur; geri kalan durum normal tablolarda kalır.
- **Ayrı vektör veritabanı yok.** pgvector yeterli; ölçülmüş bir gecikme sorunu olmadan değişmez.
- **Yeni rol, yeni ajan yok** (v10 kuralı). Mevcut roller küçültülür ya da defterden beslenir.
- **RLHF / ince ayar yok** (v10 §10). Onay ve düzeltmeler eval setine ve kurallara dönüşür.
- **Ön yüz çatısı değişmez.** Next.js 14 kalır; yükseltme ayrı ve ölçülü bir iştir.

---

## 4. Geçiş ilkeleri

1. **Boğucu incir (strangler) yolu.** Eski yol yeni yolun yanında çalışır; yeni yol aynı rakamı verdiği kanıtlanınca (gölge karşılaştırma testi) eski yol kaldırılır. Büyük patlama yok.
2. **Önce veri sözleşmesi.** Her adım `docs/data-contracts.md`'ye neyi türettiğini, kaynağını ve yeniden üretilebilirliğini yazarak başlar (v10 §13.2).
3. **Kırmızı testle başla.** Her PR bir A-adımı (bu plan) ve varsa G/M/O numarası yazar, sorunu yeniden üreten testle açılır.
4. **Pilot önce gelir.** Bir mimari adım pilot işini geciktirecekse bekler; pilotun ihtiyaç duyduğu yerde öne çekilir (ör. outbox, S1.3 bülten e-postasıyla birlikte doğar).
5. **Her adım geri alınabilir.** Yeni tablolar ekleyerek gelir; eskisi gölge dönem bitene kadar silinmez. Silme DISPATCH'tir.
6. **Ölçmeden "hazır" yok.** Bir bileşenin "hedefte" sayılması için §8'deki uygunluk testi yeşil olmalıdır.
7. **Canlı denemeden birleşmez.** Ekrana ya da veriye dokunan her adım yerel canlı koşuyla denenir; deneyemediği şey PR'da yazılır.

---

## 5. Bileşen bazlı yol haritası

Her bileşen için: bugün → hedef → adımlar → bitti ölçütü. Adım numaraları (A1.1 …) §6'daki fazlara bağlanır.

### C1 · Giriş ve ayrıştırıcılar
- **Bugün:** Ayrıştırıcı kaydı var; mizan (#50), e-Fatura, e-Defter ayrıştırılıyor. `data_ingestion.py` hem algılama, hem ayrıştırma, hem normalize, hem iş yürütme yapıyor. G25 (zip) commit'siz ağaçta güvensiz duruyor.
- **Hedef:** Tek giriş sözleşmesi: `kaynak → ayrıştırıcı → NormalizedRow(kimlik, tarih, tutar_kuruş, yön, hesap_kodu?, belge_no?, karşı_taraf?, vade?)`. Dosya, e-posta ve bağlayıcı aynı kapıdan girer.
- **Adımlar:**
  - A0.3 `data_ingestion.py`'yi dört modüle böl: algılama, ayrıştırma çağrısı, normalize, iş adımı. Davranış aynı, testler aynı.
  - A1.4 Bağlayıcılar normalize satırı aynı sözleşmeyle üretir (Paraşüt bugün `FINANSAL_BELGE` CSV'ye çevirip içeri alıyor; doğrudan satır verir).
  - A2.5 Zip yalnız sınırlarla: uzantı, toplam açılmış boyut, iç dosya sayısı, her XML `xml_safety` (G25). Gerek yoksa hiç eklenmez.
  - Sürekli: her yeni ayrıştırıcı GİB/banka resmî örneğine karşı test edilir; pilotun her dosyası külliyata girer.
- **Bitti:** Giriş modüllerinin hiçbiri 600 satırı geçmez; üç giriş kapısı da `NormalizedRow` üretir; metamorfik testler (iki kez yükle, sırayı değiştir, dosyayı böl) aynı defteri verir.

### C2 · Bağlayıcılar
- **Bugün:** Beş klasör (D7). Paraşüt çekimi belge kimliği taşıyor (G22) ama sözleşmesi doğrulanmadı (G17); `open_banking` adaptörü sahte; platform adaptörleri `canonical_eng_signals`'a yazıyor.
- **Hedef:** Tek bağlayıcı çatısı (`connectors/`): kimlik bilgisi şifreli, sağlık denetimi gerçekten uca gider, filigran yalnız başarıda ilerler, sayfalama tam, çıktı C1'in normalize satırı. Doğrulanmamış bağlayıcı varsayılan kapalı ve ekranda "doğrulanmadı" yazar.
- **Adımlar:**
  - A0.4 Envanter ve karar: beş yoldaki her bağlayıcı için "tut / taşı / sil" tablosu (ERP, GİB e-Fatura/e-Defter, Paraşüt, açık bankacılık, GitHub).
  - A1.5 Paraşüt'ü `connectors/` çatısına taşı; resmî API belgesine karşı sözleşme testi (G17). Sözleşme doğrulanana kadar özellik bayrağı kapalı.
  - A3.4 Diğerlerini taşı ya da sil; `services/connectors`, `data_sync`, `erp`, `open_banking` klasörleri boşalınca kaldırılır.
- **Bitti:** Tek klasör; her bağlayıcının sözleşme testi ve sağlık testi var; hiçbir adaptör "0 kayıt, başarılı" diye sessiz geçmez.

### C3 · Tek defter ve muhasebe (omurga)
- **Bugün:** D1. `canonical_transactions` tek taraflı (yön + kategori + bazen hesap kodu); muhasebe yevmiyesi JSON. M0 onaylı yevmiyeyi JSON'dan okuyor (`approved_journal.py`).
- **Hedef:** Tek tablo çifti: `journal_entries` (belge, tarih, dönem, kaynak, durum) + `journal_lines` (hesap kodu, borç/alacak kuruş, karşı taraf, açık kalem referansı). CFO defteri, mizan, e-Defter, P&L ve radar buradan türetilir. `canonical_transactions` önce bu tablodan beslenen bir projeksiyona, sonra bir görünüme dönüşür.
- **Adımlar:**
  - A1.1 Şema ve migration (yalnız ekleme): `journal_entries`, `journal_lines`; borç = alacak kısıtı her kayıtta.
  - A1.2 Çift yazma: muhasebe ajanının ürettiği yevmiye JSON'a ek olarak tabloya yazılır (gölge dönem). Gölge karşılaştırma testi: aynı iş için JSON mizanı ile tablo mizanı kuruşuna eşit.
  - A1.3 Okuma geçişi: e-Defter, mizan, yevmiye dökümü tablodan okur. JSON yalnız arşiv.
  - A3.1 CFO defteri yevmiyeden türer: `canonical_transactions` satırı = yevmiyenin banka/kasa/cari bacağı. Mizan ↔ P&L mutabakat testi (M3).
  - A4.x JSON yevmiye yazımı kaldırılır (DISPATCH değil, çünkü tablo silinmez; yalnız yazım durur).
- **Bitti:** Mizanın toplamı, P&L'nin toplamı ve radarın başlangıç bakiyesi aynı tablodan gelir; bir mutabakat testi bunu her CI'da kanıtlar.

### C4 · Karar günlüğü
- **Bugün:** D2. `DecisionLog` var ama yönetim önerileri için; defter kararları türetilmiş tablolarda.
- **Hedef:** `decisions` eklemeli tablo: `(id, org_id, tür, hedef_kimlik, karar, karar_veren, zaman, gerekçe, öncekinin_id)`. Türler: mükerrer, eşleşme, kategori düzeltme, yevmiye onayı/düzeltmesi, öneri yanıtı, dönem kilidi. Defter ve eşleşmeler bu günlüğü uygulayarak üretilir.
- **Adımlar:**
  - A1.6 Tablo + yazma yolu: bugünkü her karar uç noktası günlüğe de yazar (çift yazma).
  - A1.7 Geri doldurma: türetilmiş tablolardaki mevcut kararlar günlüğe taşınır (tek seferlik, tekrar çalıştırılabilir).
  - A2.1 Defter kurulumu günlüğü uygular; `test_ledger_rebuild` kararlı şirkette kararları da geri getirir (I2). Bu adımdan sonra "defter tabloları elle silinmez" kuralı kalkar.
  - A2.2 G3 bu günlük üzerinden kapanır: kategori düzeltmesi bir karar satırıdır, defter onu uygular.
- **Bitti:** Defteri sil, yeniden kur: rakamlar ve kararlar aynı. `docs/data-contracts.md` "Bilinen boşluk" bölümü silinir.

### C5 · Projeksiyonlar ve anlık görüntüler
- **Bugün:** Saf fonksiyonlar çoğunlukla var; şirket görünümü her imza değişiminde tam koşu (G11); anlık görüntü tabloları dağınık; radar tahmin günlüğü #47'de.
- **Hedef:** Her projeksiyon `f(defter, kararlar, tarih) → sonuç` imzasında, bir sürüm numarasıyla. "O gün ne görüldü" sorusu için tek desen: içerik özetli, değişmez anlık görüntü (radar tahmini bunun ilk örneği). Şirket görünümünde sayılar hemen, anlatı gecikmeli ve ayrı.
- **Adımlar:**
  - A0.1 #47'yi birleştir; desen olarak belgelenir.
  - A2.3 Şirket görünümü ikiye ayrılır: deterministik sayı projeksiyonu (her değişimde, ucuz) + LLM anlatısı (gecikmeli, kuyruklu, maliyeti ölçülen). G11.
  - A2.4 G8: projeksiyonlar dönem parametresi alır; varsayılan son 12 ay; yanıtta dönem yazar.
  - A3.2 Semantik ve kurumsallaşma anlık görüntüleri aynı desene taşınır.
- **Bitti:** Her projeksiyonun `docs/data-contracts.md` satırı ve "sil-yeniden-hesapla aynı" testi var; LLM koşusu yalnız anlatı değişimi gerektiğinde tetiklenir ve sayısı ölçülür.

### C6 · Ajan katmanı ve orkestrasyon
- **Bugün:** D5, D10. LangGraph 0.1.19; run gate ve doğrulayıcı var; rol ajanları ürünün pilot yolunda değil.
- **Hedef:** Tek ajan sözleşmesi: `girdi (defterden) → deterministik adımlar → (isteğe bağlı) LLM adımı gateway'den → doğrulayıcı → güven kapısı → AgentRun`. CFO hattı ve muhasebe hattı bu sözleşmenin iki örneği. Rol ajanları ya defterden beslenir ve güvenini ölçer (E4) ya da ürün dışına alınır (kod silinmez, kayıttan çıkar).
- **Adımlar:**
  - A0.2 Ölü kodu kaldır: `core/llm_client.py`, `services/financial_rag.py` (çağıranı yok). Az çağrılanlar için (agent_bus, agent_memory, agent_negotiation, reasoning_loop, reflection_agent, retry_with_reflection, capability_router) "tut / birleştir / sil" kararı, çağıranlarıyla birlikte.
  - A3.3 LangGraph ve LangChain'i güncel sürüme yükselt; önce bağımlılığı tek bir modülün (`platform/`) arkasına topla, sonra yükselt. Altın testler ve eval'lar aynı kalmalı.
  - A3.5 Rol ajanları (CHRO, Risk, Denetim, Uyum) için karar: pilot istemiyorsa `auto_chain`'den çıkar; istiyorsa defterden bulgu ve güven ölçümü (G13, E4).
  - A3.6 `auto_chain.py` (709 satır) ve `ceo/synthesis_agent.py` (762) küçültülür; zincir tanımı veri olur (hangi rol hangi sonucu okur), kod değil.
- **Bitti:** `agents/` altında her modülün en az bir üretim çağıranı ve testi var; yükseltilmiş LangGraph ile `pytest tests/test_agents/` yeşil (CLAUDE.md #6); her rol koşusu güven ölçüyor ya da kayıtlı değil.

### C7 · Model gateway ve yapay zeka ölçümü
- **Bugün:** 39 modül gateway kullanıyor; tek sağlayıcı; LLM'li koşu ölçülmedi (D8).
- **Hedef:** Gateway çok sağlayıcılı (OpenAI + Anthropic + yerel test modeli), model kataloğu sürümlü, her çağrı `llm_call_log`'a maliyet ve gecikmeyle yazılır. LLM'in işi sınırlı: anlatı, sınıflandırma, belge alanı çıkarma. Her LLM işinin altın kümesi var.
- **Adımlar:**
  - A3.7 E3 altın kümesi: bülten, şirket görünümü anlatısı, THP sınıflandırma, sohbet. Ölçütler: uydurma sayı 0, kapıya düşme oranı, koşu başına maliyet, p95 gecikme. Model anahtarı gerekir (sahip kararı).
  - A3.8 İkinci sağlayıcı: gateway'e eklenir, aynı altın kümeyle karşılaştırılır; seçim ölçümle yapılır.
  - A4.3 Karar kalitesi (G12): öneri beklentisi ve sonucu yapılandırılmış alan; radar tahmin notlaması (O5) ile birlikte panoda.
- **Bitti:** Her LLM işinin skor kartı CI'da (anahtarsız ortamda kayıtlı yanıtlarla) ve haftalık canlı koşuda var.

### C8 · Sohbet ve RAG
- **Bugün:** Kanıt defterden (G9); `rag_service.py`, `services/rag/`, `chat_grounding.py` üç yerde; `api/chat.py` 854 satır.
- **Hedef:** Tek geri getirme katmanı (`services/rag/`): defter kanıtı + belge parçaları + karar günlüğü; sohbet router'ı ince; her yanıt kanıt çipleriyle.
- **Adımlar:** A3.9 `rag_service` ve `chat_grounding` `services/rag/`'e birleşir; `api/chat.py` iş mantığı servise iner. Sohbet çipleri `evidence_ledger_count`'u gösterir (G9 kalan).
- **Bitti:** Router 300 satırın altında; sohbetin altın kümesi C7'de.

### C9 · Etki katmanı: outbox, zamanlayıcı, worker
- **Bugün:** D4, D6. 13 zamanlanmış iş `scheduler.py`'de; worker iki fonksiyon kümesi; e-posta sessiz atlanabiliyor.
- **Hedef:** `outbox` tablosu: `(anahtar UNIQUE, org_id, kanal, yük, durum, deneme, son_hata, gönderildi)`. İş kodu etkiyi yazmaz, outbox'a satır ekler; tek bir gönderici satırları işler. Zamanlayıcı yalnız "hangi iş ne zaman" bilgisini tutar; işlerin gövdesi servislerde.
- **Adımlar:**
  - A0.5 **Outbox, S1.3 bülten e-postasıyla birlikte doğar:** anahtar `briefing:{org}:{briefing_id}:{alıcı}`; SMTP yoksa satır `failed: smtp_not_configured` ve ekranda görünür.
  - A2.6 Bildirimler, uyarılar, Slack/WhatsApp outbox'a taşınır; `notification_service` göndericiye dönüşür.
  - A2.7 `scheduler.py` bölünür: iş kayıt tablosu (ad, cron, kilit, gövde fonksiyonu) + her işin gövdesi kendi servisinde. `worker.py` aynı şekilde.
  - A5.1 Kaos testleri: gönderici ölürse satır yeniden denenir, iki kez gönderilmez.
- **Bitti:** Hiçbir modül doğrudan SMTP/HTTP etkisi çağırmaz (mimari testi); her başarısız etki bir satır olarak görünür; `scheduler.py` 300 satırın altında.

### C10 · API katmanı
- **Bugün:** 83 router; zarf sözleşmesi; erişim denetimi rota testiyle; iş mantığı bazı router'larda.
- **Hedef:** Router = doğrulama + yetki + servis çağrısı + zarf. İş mantığı servislerde. OpenAPI ile ön yüz arasında "kapısı olmayan özellik" testi.
- **Adımlar:**
  - A2.8 Kapı testi: OpenAPI'deki her rota grubu ya ön yüzden çağrılıyor ya da bir izin listesinde gerekçeyle duruyor (makine API'si, webhook, iç). Kapısız grupların (counterfactual, cross_domain, intelligence, open_banking) her biri için "ekran ver / iç API yap / sil" kararı.
  - A3.10 En büyük router'lar (`muhasebe`, `ceo`, `org`, `compliance_extended`, `chat`) servise iner.
- **Bitti:** Hiçbir router 600 satırı geçmez; kapı testi CI'da.

### C11 · Ön yüz
- **Bugün:** 52 ekran; odak modu 8 ekran; bülten ekranı #49; i18n kısmi; konsolda `Logo` hidrasyon uyarısı; testler sahte API'ye karşı.
- **Hedef:** Pilot akışının ekranları (Başlangıç, Bağla, Radar, Bülten, Defter/P&L, Onaylar, Ayarlar) birinci sınıf: tam i18n, boş/hata/yükleniyor durumları, erişilebilirlik. Diğer ekranlar odak dışında kalır, yalnız güvenlik ve veri bütünlüğü düzeltmesi alır (v10 kuralı). API istemcisi tipleri OpenAPI'den üretilir.
- **Adımlar:**
  - A0.6 G16: menü ve pilot ekranlarının metinleri i18n'e; layout'ta sabit metin kalırsa düşen test.
  - A2.9 OpenAPI'den tip üretimi (`openapi-typescript`, bağımlılık önce `package.json`'a): elle yazılmış `lib/api/*.ts` tipleri üretilen tiplere bağlanır; sözleşme kayması derleme hatası olur.
  - A2.10 Hidrasyon uyarılarını sıfırla (ilk: `Logo`/`Wordmark`).
  - A4.4 Uçtan uca bir Playwright akışı: demo şirket → yükle → radar → bülten → yanıt. CI'da.
- **Bitti:** Pilot ekranlarında sabit metin 0, hidrasyon uyarısı 0, uçtan uca akış CI'da yeşil.

### C12 · Kimlik, kiracılık ve mali müşavir portföyü
- **Bugün:** M1 büyük ölçüde master'da (müşteri = kendi org'u, üyelik, VKN, şirket değiştirici, yetki matrisi). M4 yok.
- **Hedef:** Müşavir 10–50 müşteriyi tek ekrandan yönetir; her sorgu kiracıya bağlı; portföy görünümleri (bekleyen onaylar, vergi takvimi, dönem kilidi) müşteri başına projeksiyonların birleşimi.
- **Adımlar:**
  - A4.1 Portföy projeksiyonu: müşteri başına bekleyen onay, son belge, yaklaşan vergi; müşteri sayısıyla doğrusal ve ölçülen süre.
  - A4.2 Dönem kilidi bir karar türüdür (C4); kilitli döneme yazım reddedilir.
  - Auth ve rate-limit değişiklikleri DISPATCH'tir; plan yalnız gereksinimi yazar.
- **Bitti:** 50 müşterili sentetik portföyde portföy ekranı p95 < 1 sn (ölçülür, uydurulmaz); kiracılar arası sızıntı testi yeşil.

### C13 · Gözlemlenebilirlik
- **Bugün:** D9. `AgentRun` SLO'su, Sentry, `llm_call_log`.
- **Hedef:** Her istek ve her koşu bir trace kimliği taşır; log satırları yapılandırılmış (JSON) ve `org_id`, `job_id`, `run_id`, `trace_id` içerir; LLM maliyeti ve gecikmesi koşuya bağlanır.
- **Adımlar:**
  - A2.11 Yapılandırılmış log (standart kütüphane `logging` + JSON biçimlendirici; yeni bağımlılık gerekirse önce `requirements.txt`); `trace_id` ara katmanda üretilir ve arq işlerine taşınır.
  - A4.5 OpenTelemetry izleri staging'de; bir pano: koşu süresi, kapıya düşme oranı, outbox hataları, LLM maliyeti.
- **Bitti:** Pilotta bir sorun "bu org, bu belge, bu koşu" diye tek sorguyla izlenir.

### C14 · Altyapı ve operasyon
- **Bugün:** D11. Managed Postgres yolu yazıldı (#23), Helm üretilmedi, k8s deploy işi düzeltildi (#44).
- **Hedef:** Staging (Postgres, Redis, API, worker, ön yüz) ve üretim aynı manifestlerden; her gece yedek, ayda bir geri yükleme tatbikatı; migration'lar CI'da Postgres'e karşı (var).
- **Adımlar:**
  - A0.7 Sahip kararı: barındırma sağlayıcısı (G18). Karar gelmeden yapılacak kod işi yok; karar gelince staging bir haftalık iştir.
  - A1.8 Staging ayağa kalkar; worker ilk kez gerçek ortamda koşar; ilk geri yükleme tatbikatı yazılı runbook'la.
  - A1.9 Helm şablonu CI'da `helm template` ile üretilir ve doğrulanır.
- **Bitti:** Staging'de uçtan uca pilot akışı; tatbikat süresi ve sonucu `docs/ops/`'ta.

### C15 · Güvenlik ve uyum
- **Bugün:** Alan şifreleme, denetim ara katmanı, rate limit, güvenlik başlıkları, XML güvenliği, yükleme yasası (CLAUDE.md #9). KVKK gözden geçirmesi yok (G19).
- **Hedef:** KVKK envanteri (hangi kişisel veri, nerede, ne kadar süre), silme talebi uçtan uca (org silme tüm tablolarda, anlık görüntüler dahil), erişim günlüğü.
- **Adımlar:**
  - A1.10 Veri envanteri belgesi (`docs/kvkk-veri-envanteri.md`) koddan çıkarılır; hukuki gözden geçirme için sahibe verilir (G19 karar).
  - A2.12 Org silme testi: her tabloda org verisi kalmaz (anlık görüntüler ve outbox dahil).
- **Bitti:** Silme testi yeşil; envanter hukuki gözden geçirmeden geçmiş.

### C16 · Test ve doğrulama
- **Bugün:** `verify.py` kapısı; metamorfik ve sıfır yanlış pozitif testleri başladı; zor durum üreteci commit'siz ağaçta.
- **Hedef:** Üç halka: (1) birim/sözleşme, (2) külliyat (resmî örnekler + pilot dosyaları + zor durum üreteci), (3) uçtan uca ve kaos. Mimari uygunluk testleri (§8) CI'da.
- **Adımlar:** A0.8 mimari testleri iskelesi (katman bağımlılık yönü, dosya boyu tavanı, doğrudan etki yasağı) mevcut ihlallerle bir *ratchet* olarak başlar: yeni ihlal eklenemez, eskiler azaldıkça liste küçülür. A5.2 kaos testleri (E5).
- **Bitti:** §8'deki tüm uygunluk testleri CI'da; ratchet listeleri boş.

### C17 · Belgeler
- **Bugün:** Kökte 20'den fazla plan/mimari belgesi (G21); `docs/data-contracts.md` canlı.
- **Hedef:** Kökte yalnız README, CLAUDE.md, PRODUCT.md, DESIGN.md, PLAN_V10.md, PLAN_V11.md. Eski planlar `docs/arsiv/`'e. Mimari kararlar `docs/adr/` altında kısa kayıtlar.
- **Adımlar:** A0.9 arşivleme PR'ı (G21); A0.10 §7'deki kararlar için ilk ADR'ler.

---

## 6. Fazlar ve takvim

Fazlar v10'un sprintleriyle (S1–S4) yan yana yürür; çakışmada S kazanır.

| Faz | Hafta | Amaç | Adımlar | v10 ile ilişkisi |
|---|---|---|---|---|
| **A0 Hazırlık** | 0–2 | Zemin: ölü kod, büyük dosyaların ilki, envanterler, ratchet'ler, outbox'ın doğuşu | A0.1–A0.10 | S1 ile birlikte; outbox S1.3'te doğar |
| **A1 Omurga** | 2–6 | Tek defter tabloları (çift yazma), karar günlüğü (çift yazma), staging | A1.1–A1.10 | S2 (doğruluk) ve M3 ile aynı yönde |
| **A2 Türetme ve etkiler** | 5–9 | Defter günlüğü uygular (I2), G3/G8, görünümün sayı/anlatı ayrımı, outbox'ın yayılması, zamanlayıcı bölünmesi, kapı testi, OpenAPI tipleri, log | A2.1–A2.12 | S1 kalanları (G3, G8) burada kalıcı çözülür |
| **A3 Zeka** | 8–13 | CFO defteri yevmiyeden; ajan katmanı küçülür; LangGraph yükseltmesi; E3 ölçümü; bağlayıcılar tek çatı; RAG birleşmesi | A3.1–A3.10 | S3 (ölçüm) |
| **A4 Ölçek** | 12–16 | Müşavir portföyü, dönem kilidi, karar kalitesi, uçtan uca CI, izler | A4.1–A4.5 | S4 (müşavir operasyonu) ve Ufuk 2 |
| **A5 Dayanıklılık** | 15–18 | Kaos testleri, outbox dayanıklılığı, tatbikat rutini | A5.1–A5.2 | v10 §13 E5 |

### Kritik yol
`A1.1 şema → A1.2 çift yazma → A1.6 karar günlüğü → A2.1 defter günlüğü uygular → A3.1 CFO defteri yevmiyeden`. Bu zincir tamamlanmadan "mizan = P&L" (M3) ve "defter silinip yeniden kurulabilir" (I2) iddia edilmez.

Paralel yol: `A0.7 barındırma kararı → A1.8 staging`. Kod değil karar bekler; pilotun kritik yoludur.

---

## 7. Mimari kararlar (ADR) ve sahip kararları

| # | Karar | Önerilen | Neden | Kimin |
|---|---|---|---|---|
| K1 | Tek defter: yeni yevmiye tabloları mı, `canonical_transactions`'ı genişletmek mi | **Yeni tablolar**, `canonical_transactions` projeksiyona dönüşür | Çift taraflılık ve hesap kodu ilk günden kısıt olarak; mevcut tablo silinmez (DISPATCH yok) | Geliştirici (ADR) |
| K2 | Karar günlüğü tam olay kaynaklama mı | **Hayır**, yalnız kararlar eklemeli | Değer kararların kaybolmamasında; tam ES maliyeti karşılanmaz | Geliştirici (ADR) |
| K3 | Outbox gönderici: arq işi mi, ayrı süreç mi | **arq işi** (bakım worker'ı) | Yeni süreç yok; kilit ve yeniden deneme var | Geliştirici (ADR) |
| K4 | Model sağlayıcı | **Gateway arkasında çoklu**, seçim altın kümeyle | Tek sağlayıcı riski; ölçmeden seçim yok | Sahip (anahtar ve bütçe) |
| K5 | LangGraph yükseltmesi zamanı | **A3**, bağımlılık tek modüle toplandıktan sonra | Önce yüzeyi küçült, sonra yükselt | Geliştirici |
| K6 | Rol ajanlarının geleceği | **Pilot istemiyorsa kayıttan çıkar** (kod kalır) | v10 kuralı: kanıtsız rol yok | Sahip |
| K7 | Barındırma sağlayıcısı | Sahip seçer | G18; staging buna bağlı | Sahip |
| K8 | KVKK ve hukuki gözden geçirme | Envanter hazırlanır, sahip hukukçuya verir | G19 | Sahip |
| K9 | E-posta gönderen sağlayıcı ve alan adı | K7 ile birlikte | Gmail SMTP pilota uygun değil | Sahip |
| K10 | Müşavirli şirkette bülten e-postası müşavir onayını bekler mi | **Bekler**, ekran beklemez (SMMM D5) | "Onaysız hiçbir şey patrona gitmez" | Sahip |

DISPATCH (CLAUDE.md) gereği insana gidenler: auth ve rate-limit değişiklikleri (C12), sütun/tablo silen migration'lar (A4'teki temizlikler), `CFOState`'ten alan silen değişiklikler (C6), üretim port bağlamalarını etkileyen Compose değişiklikleri (C14).

---

## 8. Mimari uygunluk testleri (fitness functions)

Her biri bir testtir; mevcut ihlallerle *ratchet* olarak başlar.

| # | Test | Bugün | Hedef |
|---|---|---|---|
| F1 | Katman yönü: `services/` → `api/` içe aktarmaz; türetme modülleri `models`'e yazmaz (anlık görüntü deposu hariç) | ölçülecek (A0.8) | 0 ihlal |
| F2 | Dosya boyu tavanı: `app/` altında 600 satırı geçen dosya (400'ü geçen 83, 500'ü geçen 41 dosya da izlenir) | 17 dosya | 0 |
| F3 | Doğrudan dış etki yasağı: `aiosmtplib`, Slack/WhatsApp/bot HTTP çağrısı yalnız outbox göndericisinde | SMTP 1 yer (`notification_service`); bot çağrıları en az 2 yer (`notification_service`, `bot_gateways`) | yalnız gönderici |
| F4 | Kapı testi: ön yüzü olmayan rota grubu ya izin listesinde ya da yok | ~4 grup | 0 gerekçesiz |
| F5 | Ölü kod: üretim çağıranı olmayan modül | en az 2 | 0 |
| F6 | Defteri sil-yeniden kur: rakamlar **ve kararlar** aynı | rakamlar evet, kararlar hayır | ikisi de evet |
| F7 | Mizan ↔ P&L mutabakatı aynı tablodan, kuruşuna | yok | CI'da |
| F8 | Her rota kimlik + kiracı denetimi | var | var |
| F9 | LLM işleri: uydurma sayı | ölçülmedi | 0 |
| F10 | Pilot ekranlarında sabit metin / hidrasyon uyarısı | var | 0 |

---

## 9. Riskler

| Risk | Etki | Önlem |
|---|---|---|
| Mimari iş pilotu geciktirir | v10 ölçütü kaçar | İlke 4: çatışmada S kazanır; A fazları boşluklarda ve pilotun ihtiyacında |
| Çift yazma döneminde iki kaynak ayrışır | Yanlış rakam | Gölge karşılaştırma testi her CI'da; ayrışma bir hata olarak düşer |
| LangGraph yükseltmesi davranışı değiştirir | Ajan çıktıları kayar | Önce yüzey küçültme, altın testler ve eval'lar sabit, yükseltme ayrı PR |
| Aynı çalışma ağacında başka bir aktörün işi | Çakışma, kaybolan iş | Her iş master'dan açılan ayrı worktree'de; dosyalar tek tek eklenir |
| Sahip kararları gecikir (K4, K7–K10) | Staging, ölçüm ve e-posta bekler | Kararlar §7'de açıkça; kod işi kararsız ilerleyen kısımlarla sürer |
| Ratchet'ler geliştirmeyi yavaşlatır | Sürtünme | Yeni ihlal yasak, eskiler zamanla; liste her PR'da küçülür |

---

## 10. Sıradaki adım

1. Açık PR'ları birleştir: #46 (plan §16), #47 (tahmin günlüğü, A0.1), #49 (bülten ekranı).
2. **A0.2** ölü kodun kaldırılması ve az çağrılan yardımcı zeka modülleri için karar tablosu (küçük, risksiz, hemen).
3. **A0.8** mimari testleri iskelesi: F1–F5 ratchet olarak; bugünkü sayılar bu belgeye işlenir.
4. **A0.5** S1.3 bülten e-postası, outbox'ın ilk tüketicisi olarak (K10 kararı gerekir).
5. Sahip kararları: K4 model anahtarı, K7 barındırma, K8 KVKK, K9 e-posta sağlayıcısı, K10 müşavir onayı.
