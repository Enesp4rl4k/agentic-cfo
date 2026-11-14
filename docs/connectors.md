# Bağlayıcı envanteri ve kararlar

*Plan v11 A0.4 (C2). 2026-11-14'te `origin/master` (`87a99fa`) üzerinden koddan çıkarıldı: her satırın çağıranı içe aktarma taramasıyla, ön yüz kapısı `frontend/src` içindeki API yollarıyla, defter yazımı kodda `ingest.ekle` / `run_data_ingestion` / `append_job` kullanımıyla bulundu. Bu belge bugünkü durumu ve kararı yazar; uygulama plan v11'in ilgili adımlarındadır.*

## Kısa sonuç

- Dış sistemlere bağlanan kod **beş klasör artı dokuz tek dosyada**: `connectors/`, `services/connectors/`, `services/data_sync/`, `services/erp/`, `services/open_banking/`, `gib_efatura.py`, `gib_edefter*.py`, `github_connector.py`, `integrations.py`, `scheduled_sync.py`, `email_parser.py`, `open_banking_reconciliation.py`, `erp_sync_runner.py`.
- Aynı dış sistem için **paralel yollar** var: Paraşüt için 2 istemci, açık bankacılık için 3 katman, GitHub için 3 yol.
- **`services/data_sync/` paketinin tamamı (~2.280 satır) üretimde hiçbir yerden çağrılmıyor.** İkinci Paraşüt istemcisi ve PSD2 banka istemcisi bu pakette. `scheduler.py`'deki "data_sync" eşleşmesi yalnız bir iş adı (`scheduled_data_syncs`).
- Finans defterine giden **fiilî tek kapı** `services/ingest/ekle.py`: canlı bağlayıcıların hepsi (Paraşüt, Logo/Mikro CSV, e-posta gelen kutusu, açık bankacılık uçları, veri bağlama) buradan giriyor. Plan v11 C1'in "tek giriş sözleşmesi" bu modülün üstüne kurulur.
- Bağlayıcı platformu (`connectors/`) iyi tasarlanmış (port/adaptör, şifreli sırlar, idempotent yazım) ama tek adaptörü GitHub ve **finans defterine değil** `canonical_eng_signals`'a yazıyor.

## Envanter (dış sisteme göre)

Sütunlar: **Kapı** = ön yüzde bu bağlayıcıyı çağıran bir ekran var mı. **Defter** = verisi finans defterine ulaşıyor mu. **Sözleşme** = dış API'nin resmî belgesine karşı test var mı.

### Paraşüt (pilot yolunda)

| Modül | Satır | Çağıran | Kapı | Defter | Test | Sözleşme | Karar |
|---|---|---|---|---|---|---|---|
| `services/erp/parasut_connector.py` | 459 | `api/erp_integrations` (`/erp/parasut/*`), `erp_sync_runner` (oto senkron), `scheduled_sync` | Var (`ParasutKarti`) | Evet, `ekle` üzerinden fatura olarak (G22) | 2 dosya | **Yok** (G17) | **Tut**, A1.5'te `connectors/` çatısına taşı; resmî API belgesine karşı sözleşme testi; doğrulanana kadar ekranda "doğrulanmadı" |
| `services/data_sync/accounting/parasut.py` | 352 | Yok (yalnız ölü `data_sync.orchestrator`) | Yok | — | 0 | Yok | **Sil** |

### Logo Tiger, Mikro, Netsis (muhasebe programları)

| Modül | Satır | Çağıran | Kapı | Defter | Test | Sözleşme | Karar |
|---|---|---|---|---|---|---|---|
| `services/erp/logo_tiger_connector.py` | 322 | `api/erp_integrations` (`/erp/logo-tiger/connect`), `scheduled_sync` | Var | Bağlayıcı değil: `/erp/logo-tiger/sync` bir CSV yüklemesidir ve `islemleri_ekle` üzerinden girer; bağlayıcı yalnız bağlantı kaydı ve zamanlanmış çekimde | **0** | Yok | **Tut, önce test**: canlı bir Logo örneğiyle test yazılmadan pilot yoluna girmez; A3.4'te taşı |
| `/erp/mikro/sync` (`api/erp_integrations._csv_sync`) | — | Ekran | Var | `ekle` üzerinden | parser testleri | CSV biçimi | **Tut** (dosya yolu, API değil) |
| `services/data_sync/accounting/importers.py` | 241 | Yok | Yok | — | 1 | — | **Sil** (CSV yolu zaten `ekle`'de) |
| `services/erp/two_way_sync.py` | 97 | Yok | Yok | — | 1 | — | **Sil** (muhasebeye geri yazma; sahip isteği ve sözleşme olmadan yapılmaz) |

### Açık bankacılık (Akbank, Garanti, …)

| Modül | Satır | Çağıran | Kapı | Defter | Test | Sözleşme | Karar |
|---|---|---|---|---|---|---|---|
| `services/open_banking/` (`base`, `akbank`, `garanti`) | 443 | `api/open_banking` (`/open-banking/*`) | **Yok** | Uç `ekle` çağırıyor | **0** | Yok | **Tek yol bu olur, varsayılan kapalı**: banka seçimi ve sözleşme sahip kararı (aşağıda); kapı testi (A2.8) bunu "iç API, kapalı" diye listeler |
| `services/integrations.py` → `TurkiyeOpenBankingClient` | (453 içinde) | `scheduled_sync` (`OPEN_BANKING` kaynağı) | Yok (`/sync/*` için ekran yok) | Evet, `scheduled_sync` üzerinden | 0 | Yok | **Sil**, zamanlanmış çekim `services/open_banking/`'e bağlanır |
| `services/data_sync/banking/psd2.py` | 447 | Yok | Yok | — | 0 | Yok | **Sil** |
| `services/open_banking_reconciliation.py` | 157 | Yok | Yok | — | 1 | — | **Sil**; mutabakat `services/reconciliation.py`'de tek yerde |
| Ana klasördeki commit'siz `connectors/open_banking.py` | — | — | — | — | — | **Sahte** (G24) | **Alınmaz** |

### GİB (e-Fatura, e-Arşiv, e-Defter)

| Modül | Satır | Çağıran | Kapı | Defter | Test | Sözleşme | Karar |
|---|---|---|---|---|---|---|---|
| `services/gib_efatura.py` | 414 | `api/efatura` (`/efatura/status`, `/efatura/sync`), `scheduled_sync` | Var (`EFaturaCard`) | Hayır (GİB kutusundan çekim; belge yükleme yolu ayrı) | 1 | **Yok**; hafıza notu "uydurma API kararı" (hardening-plan) | **Tut, varsayılan kapalı**: GİB'in ya da bir özel entegratörün resmî belgesine karşı sözleşme testi olmadan açılmaz (sahip kararı) |
| `services/gib_edefter.py` | 135 | `api/muhasebe` | Var (muhasebe) | Defterden türetir (çıktı) | 1 | GİB paketine karşı (var) | **Tut** |
| `services/gib_edefter_ws.py` | 249 | Yok (bilinçli) | Yok | — | 1 | `GibWsNotConfigured`, imzasız çağrı yok (`proof.sh` denetler) | **Tut, kapalı**: imza altyapısı gelene kadar çağrılmaz |

### GitHub (CTO rolü; pilot yolunda değil)

| Modül | Satır | Çağıran | Kapı | Defter | Test | Karar |
|---|---|---|---|---|---|---|
| `connectors/github.py` | 179 | `connectors.registry` (platform) | Var (`/connectors`) | `canonical_eng_signals` | 1 | **Tut**: platformun örnek adaptörü |
| `services/github_connector.py` | 314 | `api/integrations_github`, `connectors.github`, `github_activity` | (istemci) | — | 2 | **Tut**: ortak HTTP istemcisi |
| `services/connectors/github_activity.py` | 65 | `scheduled_sync` | Yok | CTO anlamsal katmanı | 1 | **Birleştir**: zamanlanmış çekim platform koşucusuna (`connectors/runner`) geçince sil |

### Fatura, CRM, İK dışa aktarımları (rol verisi; pilot yolunda değil)

| Modül | Satır | Çağıran | Kapı | Test | Karar |
|---|---|---|---|---|---|
| `services/connectors/billing_stripe.py` | 87 | `scheduled_sync` | Yok | 0 | **Rol kararına bağlı** (plan v11 K6): pilot istemezse kayıttan çıkar |
| `services/connectors/crm_export.py` | 128 | `scheduled_sync` | Yok | 1 | Aynı |
| `services/connectors/hr_export.py` | 98 | `scheduled_sync` | Yok | 1 | Aynı |
| `services/connectors/{registry,csv_utils}.py` | 86 | yukarıdakiler | — | 1 | Yukarıdakilerle birlikte |

### Pazar yerleri, Google Sheets, webhook

| Modül | Çağıran | Kapı | Test | Karar |
|---|---|---|---|---|
| `integrations.ShopifyConnector`, `TrendyolConnector`, `GoogleSheetsConnector` | `api/integrations_extended` | Doğrulanmadı (kapı testi A2.8 karar verir) | 0 | **Kapalı tut**; pilot isterse platform çatısına taşı |
| `integrations.HepsiburadaConnector` | Yok | Yok | 0 | **Sil** |
| `integrations.WebhookDispatcher` | `api/org` | — | 0 | Bir **dış etkidir**: outbox'a taşınır (plan v11 A2.6) |

### Giriş kapıları ve zamanlayıcı

| Modül | Satır | Rol | Karar |
|---|---|---|---|
| `services/ingest/ekle.py` | 358 | Finans defterine tek kapı; 6 üretim çağıranı, 4 test dosyası | **Tut, merkez**: plan v11 C1'deki `NormalizedRow` sözleşmesi buradan büyür |
| `services/email_parser.py` | 353 | E-posta gelen kutusu (`api/email_ingest`, `EpostaKutusu` ekranı) → `ekle` | **Tut** (giriş kapısı) |
| `agents/orchestration/erp_sync_runner.py` | 90 | Paraşüt oto senkronu (zamanlayıcı) → `ekle` | **Tut**; A1.5'te platform koşucusuna katılır |
| `services/scheduled_sync.py` | 1.023 | Yedi kaynak türü için zamanlanmış çekim; `/sync/*` uçlarının ekranı yok | **Böl** (A2.7): kaynak başına gövde kendi bağlayıcısına; silinen kaynaklar buradan da çıkar |
| `connectors/{base,registry,runner,crypto}.py` | 393 | Platform çatısı | **Hedef çatı**; `runner` finans için `ekle`'ye yazan bir hedef kazanır (A1.4) |

## Kararların özeti

| Karar | Modüller | Satır (yaklaşık) | Adım |
|---|---|---|---|
| **Sil** (üretim çağıranı yok) | `services/data_sync/` paketi tümüyle, `erp/two_way_sync.py`, `open_banking_reconciliation.py`, `integrations.HepsiburadaConnector` | ~2.560 | A0.4b (hemen, risksiz) |
| **Sil, yerine tek yol** | `integrations.TurkiyeOpenBankingClient` (→ `services/open_banking/`), `github_activity` (→ platform koşucusu) | ~170 | A3.4 |
| **Taşı** `connectors/` çatısına | Paraşüt, Logo Tiger, açık bankacılık, GİB e-Fatura | ~1.640 | A1.5 (Paraşüt), A3.4 (diğerleri) |
| **Kapalı tut** (sözleşme yok) | GİB e-Fatura senkronu, açık bankacılık, pazar yerleri, Sheets | — | sahip kararı |
| **Rol kararına bağlı** | Stripe, CRM, İK dışa aktarımları | ~400 | K6 |
| **Tut** | `ingest/ekle`, `email_parser`, `gib_edefter*`, GitHub istemcisi ve adaptörü, platform çatısı | — | — |

## Sahip kararları

1. **Hangi banka?** Pilot şirketlerin bankası belli olunca o bankanın açık bankacılık belgesine karşı sözleşme testi yazılır; o zamana kadar banka verisi ekstre dosyasıyla gelir (bugün çalışan yol).
2. **GİB e-Fatura kutusundan çekim:** GİB'in kendisi mi, bir özel entegratör mü? Resmî belge olmadan bu senkron açılmaz.
3. **Logo / Mikro önceliği:** pilot şirketler hangi programı kullanıyor? Kullanılan program için canlı örnekle test yazılır; diğerleri dosya yüklemeyle kalır.

## Uygulama sırası

1. **A0.4b**: üretim çağıranı olmayanları sil (yukarıdaki ilk satır). `test_architecture_fitness.py` F5 listesinden `data_sync.orchestrator`, `data_sync.scheduler`, `erp.two_way_sync`, `open_banking_reconciliation` çıkar.
2. **A1.4–A1.5**: `connectors/runner` için finans hedefi (`ekle`), Paraşüt'ün taşınması ve sözleşme testi.
3. **A2.7**: `scheduled_sync.py`'nin kaynak başına bölünmesi.
4. **A3.4**: kalan taşımalar ve silmeler; `services/connectors`, `services/erp`, `services/open_banking` klasörleri boşalınca kaldırılır.
