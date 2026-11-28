# Kişisel Veri Envanteri

> **TASLAK — hukukçu incelemesi gerekir.** Bu envanter kodun `master` @ `61747c8` hâlinden
> çıkarıldı. Kod hakkındaki her iddia `yol:satır` ile kaynak gösterir; satır numaraları bu
> commit içindir. Hukuki sınıflandırmalar (m.5 hukuki sebep, saklama süresi) **öneridir**.
> Karar bekleyen konular: [acik-konular.md](acik-konular.md).

## 1. Özet — dört cümle

1. Veri Türkiye'deki sunucuda tutulur; ama **LLM çağrıları yurt dışına gider ve varsayılan
   sağlayıcı DeepSeek'tir (Çin)**, OpenAI değil (`backend/app/config.py:218`).
2. LLM istemine gönderilmeden önce **hiçbir maskeleme yoktur**; karşı taraf adları, banka/fatura
   açıklamaları, yüklenen belgenin ham metni ve kullanıcının serbest metin soruları gidebilir (§4).
3. **Hiçbir tablo için otomatik saklama/silme yoktur**; yüklenen dosyalar süresiz kalır (§6).
4. Kiracı ayrımı tek bir kuralla ve bütün rotalarda uygulanır (`backend/app/api/access.py:42`).

## 2. Kim erişir — roller ve kiracı ayrımı

- **Kural:** organizasyonu olan bir kayıt yalnız o organizasyonun kullanıcılarına görünür;
  organizasyonu olmayan kayıt yalnız oluşturan kullanıcıya (`backend/app/api/access.py:42-48`).
  Başkasının kaydı 404 döner (`backend/app/api/access.py:19-20`). Bütün rotalar bu kurala
  karşı test edilir (`backend/app/api/access.py:22-26`, `backend/tests/test_route_access.py`).
- **Organizasyon içi roller:** owner, admin, cfo, analyst, viewer, smmm
  (`backend/app/models/user.py:31-40`). SMMM müşterinin organizasyonuna katılır, owner/admin/cfo
  yetkisi almaz (`backend/app/models/user.py:37-40`). Bir kullanıcı birden çok organizasyona
  üyelikle bağlanabilir (`backend/app/models/organization.py:119-138`).
- **Rol ayrımı yalnız yönetim işlemlerinde var:** üye/davet yönetimi owner/admin
  (`backend/app/api/org.py:70-77`), bazı işlemler yalnız owner (`backend/app/api/org.py:80-85`),
  pilot davetleri admin/owner (`backend/app/api/pilot.py:62-65`). **Finansal verinin okunması
  için roller arasında fark yoktur** — viewer da işlem açıklamalarını ve karşı tarafları görür.
  Aşağıdaki tablolarda "Org üyeleri" bu anlamdadır.
- **Platform operatörü:** veritabanına ve `uploads/` diskine sunucu erişimi olan herkes her şeyi
  görür. Uygulama içinde "süper admin" rolü yoktur; bu erişim idari tedbirle (erişim listesi,
  kayıt) sınırlanmalıdır.

## 3. Veritabanı tabloları (`backend/app/models/`)

Kısaltmalar — **Yurt dışı:** "LLM" = alan §4'teki çağrılardan biriyle LLM istemine girebilir.
**m.5:** c = sözleşmenin ifası, ç = hukuki yükümlülük, f = meşru menfaat, e = hakkın tesisi/korunması.

### 3.1 Kimlik, hesap, organizasyon

| Tablo | Kişisel veri (alan) | Amaç | m.5 | Saklama önerisi | Erişim | Yurt dışı? |
|---|---|---|---|---|---|---|
| `users` | e-posta `backend/app/models/user.py:49`, parola özeti `:50`, ad-soyad `:51`, API anahtarı `:67`, SSO kimliği `:70-71`, son giriş `:72-75` | Hesap, kimlik doğrulama | c | Hesap kapanınca +90 gün | Kullanıcının kendisi; org admin üye listesinde | Hayır (ad ve e-posta LLM'e gitmez; SSO girişinde Microsoft/Google ile OAuth — `backend/app/services/sso.py:67-81`) |
| `organizations` | şirket adı `backend/app/models/organization.py:38`, VKN `:59`, ticari unvan `:60`, Stripe müşteri kimliği `:72-73` | Kiracı, faturalama | c | Sözleşme + 10 yıl (faturalama) | Org üyeleri | **LLM:** şirket adı CEO/ajan sohbet ve SWOT istemlerine girer (`backend/app/api/chat.py:466`, `backend/app/agents/ceo/swot_agent.py:380`, `backend/app/agents/compliance/orchestrator.py:333`). Şahıs şirketinde unvan = kişi adı |
| `org_invites` | davet e-postası `backend/app/models/organization.py:103`, token `:107` | Üye daveti | c | Kabul/sona ermeden 30 gün sonra | owner/admin | Hayır |
| `org_memberships` | kullanıcı–org–rol ilişkisi `backend/app/models/organization.py:132-138` | Yetki | c | Üyelik bitince 90 gün | owner/admin | Hayır |
| `pilot_invites` | e-posta `backend/app/models/pilot.py:35`, not (şirket adı) `:36` | Pilot daveti | c / f | Pilot sonu +1 yıl | admin/owner (`backend/app/api/pilot.py:62`) | Hayır |
| `user_feedback` | serbest metin yorum `backend/app/models/pilot.py:79-81`, puanlar `:68-76` | Ürün geliştirme | f | 2 yıl | Platform | Hayır |
| `smmm_muhasebeci` | unvan (ör. "SMMM Ahmet Yılmaz") `backend/app/models/smmm_portal.py:31`, vergi no `:32`, oda no `:33`, firma `:34`, il `:35`, telefon `:36` | SMMM portal hesabı | c | Hesap kapanınca +90 gün | SMMM'nin kendisi | Hayır |
| `smmm_musteri_kayit` | müşteri firma adı `backend/app/models/smmm_portal.py:70`, vergi no `:71`, il `:74`, serbest not `:86` | SMMM'nin müşteri listesi | c | İlişki bitince 90 gün | İlgili SMMM | Hayır |

### 3.2 Finansal kayıtlar — karşı taraf verisi burada

Faturadaki alıcı/satıcı ve banka hareketindeki karşı taraf **gerçek kişi olabilir**
(şahıs şirketi, serbest meslek makbuzu, maaş/kira ödemesi). VKN/TCKN fatura ayrıştırıcısında
okunur (`backend/app/parsers/invoice/ubl_tr.py:277-288`, `backend/app/parsers/invoice/makbuz.py:294-298`).
Banka ekstresinde IBAN, başlık bölümünde ve açıklama metninde bulunur
(`backend/app/services/ingest/table.py:4`); ayrı bir IBAN sütunu yoktur ama açıklamada saklanır.

| Tablo | Kişisel veri (alan) | Amaç | m.5 | Saklama önerisi | Erişim | Yurt dışı? |
|---|---|---|---|---|---|---|
| `transactions` | açıklama `backend/app/models/transaction.py:55`, satıcı `:56`, karşı taraf `:86`, ödeme notu `:85`, **belgenin ham metni** `:71` (80.000 karaktere kadar, `backend/app/worker.py:735`) | Gelir/gider kaydı, raporlama | ç / f | VUK: 5 yıl + cari yıl (acik-konular §2); `raw_text` ham dosyayla birlikte | Org üyeleri | **LLM:** açıklama ve satıcı (§4 #3, #4, #9), ham metin (§4 #1, E2–E3) |
| `canonical_transactions` | karşı taraf `backend/app/models/canonical_transaction.py:57`, açıklama `:58` | Tek defter (ledger) | ç / f | `transactions` ile aynı | Org üyeleri | **LLM:** karşı taraf + açıklama[:120] sohbet kanıtı olarak (`backend/app/services/rag/ledger_evidence.py:62-67`) |
| `open_items` | karşı taraf `backend/app/models/open_item.py:36`, açıklama `:37`, ödeme notu `:45`, e-Fatura UUID `:34` | Alacak/borç takibi | ç / f | `transactions` ile aynı | Org üyeleri | Dolaylı (aynı karşı taraf adı ledger'dan gider) |
| `open_item_matches` | eşleştiren kullanıcı `backend/app/models/open_item_match.py:36` | Fatura–ödeme eşleşmesi | f | `transactions` ile aynı | Org üyeleri | Hayır |
| `related_parties` | ad `backend/app/models/related_party.py:55`, normalize ad `:59`, ilişki türü `:61`, **VKN/TCKN** `:65`, not `:66` | İlişkili taraf işlemlerinin ayrılması | ç / f | İlişki bitince + 5 yıl | Org üyeleri | Hayır (doğrudan istem yok) |
| `smmm_onay_kayitlari` | orijinal kayıt (JSON) `backend/app/models/smmm_onay.py:69`, onay notu `:79`, düzeltme açıklaması `:84`, işlem açıklaması `:93` | SMMM onayı/düzeltmesi | ç | `transactions` ile aynı | Org üyeleri (SMMM dahil) | Hayır (açıklama THP sınıflandırıcısına başka yoldan gider, §4 #3) |
| `smmm_hesap_kurallari` | anahtar (satıcı adı olabilir) `backend/app/models/smmm_hesap_kurali.py:32` | Hesap kodu kuralı | f | Kural silinene kadar | Org üyeleri | Hayır |
| `category_rules` | satıcı eşleşmesi `backend/app/models/category_rule.py:36`, anahtar kelime `:38` | Kategori kuralı | f | Kural silinene kadar | Org üyeleri | Hayır |
| `anomalies` | başlık `backend/app/models/anomaly.py:61` ve açıklama `:62` satıcı adı içerir (ör. "Possible duplicate payment: {vendor}", `backend/app/agents/anomaly_agent.py:120-122`) | Anomali tespiti | f | 1 yıl | Org üyeleri | **LLM** (§4 #9, #13, #4) |
| `reports` | rapor JSON'u `backend/app/models/report.py:48`, dosya yolu `:45` (karşı taraf adları içerebilir) | Rapor | c | `transactions` ile aynı | Org üyeleri | Hayır |
| `analysis_jobs` | dosya adı `backend/app/models/analysis_job.py:55`, dosya yolu `:56`, kullanıcı `:60`, iş kayıtları `:86` | Yükleme işi | c | Ham dosya ile aynı | Org üyeleri | Hayır |
| `data_sources` | dosya adı `backend/app/models/data_source.py:132`, yol `:133` | Ek veri kaynağı | c | Ham dosya ile aynı | Org üyeleri | Hayır |
| `rag_chunks` | **belge ham metninin parçaları** `backend/app/models/rag_chunk.py:51`, gömme vektörü `:53` | Sohbette kanıt arama | f | Ham dosya ile aynı | Org üyeleri | **LLM:** metin gömme için gönderilir (§4 E2–E3), sohbette kanıt olarak (§4 #5, #7) |
| `decision_logs` | gerekçe `backend/app/models/decision_log.py:44`, sonuç notu `:55`, oluşturan `:60` | Karar takibi | f | 2 yıl | Org üyeleri | Hayır |
| `defensibility_packets` | paket içeriği `backend/app/models/defensibility_packet.py:46`, SMMM beyanı `:48` | SMMM savunma paketi | ç | `transactions` ile aynı | Org üyeleri | Hayır |
| `company_context_snapshots`, `company_semantic_snapshots`, `institutionalization_snapshots` | türetilmiş göstergeler (`backend/app/models/company_semantic_snapshot.py:54-57`) — çoğunlukla toplu tutar | Şirket bağlamı | f | 1 yıl | Org üyeleri | Toplu göstergeler LLM'e gider (§4 #5) |

### 3.3 Bildirim, entegrasyon, e-posta

| Tablo | Kişisel veri (alan) | Amaç | m.5 | Saklama önerisi | Erişim | Yurt dışı? |
|---|---|---|---|---|---|---|
| `alert_preferences` | e-posta alıcıları `backend/app/models/alert_preference.py:57`, **WhatsApp numarası** `:63`, Slack webhook `:49` | Bildirim | c | Ayar silinene kadar | Org üyeleri | **Evet**, kanal açılırsa: SMTP (varsayılan Gmail), Meta/Twilio, Slack — §5 |
| `alert_history`, `in_app_notifications`, `proactive_alerts` | mesaj metni (`backend/app/models/alert_rule.py:78`, `backend/app/models/in_app_notification.py:40`, `backend/app/models/proactive_alert.py:29-30`), onaylayan `backend/app/models/alert_rule.py:83` | Uyarı | f | 1 yıl | Org üyeleri | Uyarı metni seçilen kanala gider (§5); sabah özetinde LLM'e (§4 #24) |
| `email_ingest_addresses` | oluşturan kullanıcı `backend/app/models/email_ingest.py:40` | Veri alma adresi | c | İptalden 90 gün sonra | Org üyeleri | Hayır |
| `email_ingest_messages` | **gönderen e-posta adresi** `backend/app/models/email_ingest.py:52`, konu `:53` | Gelen e-postayla belge alma | c | 1 yıl | Org üyeleri | Hayır (ek dosya `transactions` yoluna girer) |
| `erp_integrations`, `erp_sync_logs` | şifreli erişim/yenileme token'ı `backend/app/models/erp_integration.py:47-48`, şifreli ayar `:53`, hata metni `:61`, `:125` | Paraşüt vb. senkronu | c | Bağlantı kesilince sil | Org üyeleri | Hayır (Paraşüt TR; veri *çekilir*) |
| `connector_connections` | şifreli sır `backend/app/models/connector_connection.py:40`, görünen ad `:35` | GitHub vb. bağlantı | c | Bağlantı kesilince sil | Org üyeleri | Hayır (GitHub'dan yalnız GET) |
| `canonical_eng_signals` | **aktör (GitHub kullanıcı adı)** `backend/app/models/canonical_eng_signal.py:59`, başlık `:60` | Mühendislik göstergeleri | f | 1 yıl | Org üyeleri | Yalnız sayımlar LLM'e gider (§4 #37) |
| `sync_schedules`, `sync_runs`, `sync_audit_logs` | kaynak ayarı `backend/app/models/sync_schedule.py:30`, hata metinleri | Zamanlanmış senkron | c | 1 yıl | Org üyeleri | Hayır |
| `trigger_definitions`, `trigger_runs` | kural, sonuç metni `backend/app/models/trigger.py:47-54`, `:118` | Otomasyon | c | 1 yıl | Org üyeleri | Hayır |

### 3.4 Kayıt ve işletim tabloları

| Tablo | Kişisel veri (alan) | Amaç | m.5 | Saklama önerisi | Erişim | Yurt dışı? |
|---|---|---|---|---|---|---|
| `audit_logs` | kullanıcı kimliği `backend/app/models/audit_log.py:40`, **e-posta** `:41`, rol `:42`, istek gövdesi `:47` (parola/token maskeli, `backend/app/middleware/audit.py:39-50`), **IP adresi** `:51` (`backend/app/middleware/audit.py:131`), tarayıcı bilgisi `:52` | Güvenlik, denetim izi | f / ç | 2 yıl | Platform; org içi görüntüleme `[kontrol edilmeli]` | Hayır |
| `llm_call_logs` | yalnız meta veri: görev, model, token, maliyet, hata metni (`backend/app/models/llm_call_log.py:32-45`). **İstem/yanıt metni saklanmaz** | LLM maliyet/işletim | f | 1 yıl | Platform | Hayır |
| `agent_jobs`, `agent_runs` | iş girdisi JSON `backend/app/models/agent_job.py:67` (kullanıcının gönderdiği metin olabilir), hata `:76`, düğüm geçmişi `backend/app/models/agent_run.py:37` | İş takibi | c | 1 yıl | Org üyeleri | Girdi, ilgili ajan çağrısıyla LLM'e gider (§4) |
| `agent_conflicts` | ajan iddiaları JSON `backend/app/models/agent_conflict.py:37-40` | Ajan çelişkileri | f | 1 yıl | Org üyeleri | Hayır |
| `compliance_certifications` | onaylayan adı `backend/app/models/compliance_extended.py:38`, unvanı `:39` | Uyum beyanı | ç | 10 yıl | Org üyeleri | Hayır |
| `breach_notifications` | ihlal açıklaması `backend/app/models/compliance_extended.py:71`, etkilenen kişi sayısı `:73` | KVKK ihlal kaydı | ç | 10 yıl | Platform | Hayır |
| `alert_rules`, `authority_policies`, `sync_schedules`, `trigger_definitions` (ayar) | kişisel veri yok veya yalnız serbest not (`backend/app/models/authority_policy.py:32`) | Ayar | c | Silinene kadar | Org üyeleri | Hayır |

## 4. LLM'e giden veri — yurt dışı aktarım (KVKK m.9)

### 4.1 Tek giriş noktası ve ayarlar

- **Alıcı:** `ChatOpenAI` istemcisi `base_url=settings.llm_base_url` ile kurulur
  (`backend/app/platform/model_gateway.py:252-258`). `llm_base_url` varsayılanı
  **`https://api.deepseek.com`** (`backend/app/config.py:218`); `.env.example:11-12` aynı.
  OpenAI yalnızca bu değer boşaltılır veya `https://api.openai.com/v1` yapılırsa kullanılır
  (`backend/app/config.py:216-217`). **Her iki durumda da yurt dışı aktarımdır** (Çin / ABD).
- **Tutarsızlık (mühendislik notu):** gateway'in model kataloğu yalnız `gpt-*` adları içerir
  (`backend/app/platform/model_catalog.py:60-65`); `LLM_MODEL=deepseek-chat`
  (`backend/app/config.py:213`) gateway tarafından kullanılmaz. Yani varsayılan ayarla
  DeepSeek uç noktasına `gpt-4o` adıyla istek gider. Staging/prod'da hangi sağlayıcının
  gerçekten yanıt verdiği ortam değişkenlerinden doğrulanmalıdır (acik-konular §1).
- **Maskeleme yok:** istem; sistem istemi + geçmiş + kullanıcı istemi olarak olduğu gibi
  gönderilir (`backend/app/platform/model_gateway.py:261-273`, `:290-298`).
- **Kapatma anahtarı:** API anahtarı boş veya `llm-placeholder-*` ise ağ çağrısı yapılmadan
  `LLMUnavailable` fırlatılır ve çağıranlar şablon metne düşer
  (`backend/app/platform/model_gateway.py:77-80`, `:247-248`). Varsayılan anahtar
  `llm-placeholder-dev`dir (`backend/app/config.py:57`). Organizasyon bazlı rıza/kapatma bayrağı
  **yoktur**.
- **Kayıt:** her çağrı `llm_call_logs`'a yalnız meta veriyle yazılır
  (`backend/app/platform/model_gateway.py:306-342`); istem metni saklanmaz.
- **Gateway dışı tek yol — gömme (embedding):** `OpenAIEmbeddings` aynı `llm_base_url`'e
  doğrudan gider (`backend/app/services/rag_service.py:131-147`); `rag_embedding_enabled`
  varsayılan açık (`backend/app/config.py:235`).

### 4.2 Hangi alan hangi çağrıyla gidiyor

Kısaltmalar: **KT** = karşı taraf/satıcı adı · **AÇK** = işlem/banka açıklaması ·
**HAM** = yüklenen belgenin ham metni (KT, VKN/TCKN, IBAN, kişi adları içerebilir) ·
**SOR** = kullanıcının serbest metni · **TOP** = yalnız toplu tutar/oran.

**Kişisel veri taşıyabilen çağrılar:**

| # | Çağrı | Özellik | İsteme giren alanlar | Sınıf |
|---|---|---|---|---|
| 1 | `backend/app/agents/data_ingestion.py:269` | Ayrıştırıcı tanımadığında LLM ile işlem çıkarma | `raw_text[:8000]` (`:272`) | **HAM** |
| 2 | `backend/app/parsers/banks/generic.py:251-258` | Son çare banka ekstresi ayrıştırma (üretim yolunda devre dışı, `:243-247`) | `text[:6000]` | **HAM** |
| 3 | `backend/app/services/accounting/thp_classifier.py:391` | Tekdüzen Hesap Planı sınıflandırması | açıklama, tutar, tür, satıcı (`:377-385`) | **AÇK, KT** |
| 4 | `backend/app/agents/chat_agent.py:343`, `:406` | CFO sohbeti | son 30 işlem: tarih, tür, kategori, tutar, `description[:40]` (`backend/app/agents/chat_agent.py:89-106`), anomali başlıkları, soru, geçmiş | **SOR, AÇK**, KT (anomali başlığında) |
| 5 | aynı, `/chat/agent` (`backend/app/api/chat.py:687-693`, `:737-743`) | Genel ajan sohbeti | şirket adı (`backend/app/api/chat.py:466`), KPI'lar, uyarılar; ledger kanıtı `"{tarih} {yön} {tutar} {karşı taraf} · {açıklama[:120]}"` (`backend/app/services/rag/ledger_evidence.py:62-67`); ham metin parçaları; 20 tura kadar geçmiş (`backend/app/api/chat.py:639-645`) | **SOR, KT, AÇK, HAM** |
| 6 | `backend/app/agents/chat_agent.py:381`, `:435` | CEO sohbeti | #4 + istemcinin gönderdiği yönetici bağlamı | **SOR, AÇK** |
| 7 | `backend/app/api/ws_stream.py:30` (`:41-101`, `:182`) | WebSocket sohbeti | gelir/marj + #5'teki kanıt | **SOR, KT, AÇK, HAM** |
| 8 | `backend/app/agents/nl_query_engine.py:271`, `:362` | Doğal dilde KPI sorgusu | soru + sonuç değeri `[:300]` (anomali listesi olabilir, `:201-203`) | **SOR**, KT olabilir |
| 9 | `backend/app/api/anomalies.py:326` | Anomali kök neden analizi | 10 ilgili işlem: tarih, **satıcı**, kategori, tutar, **açıklama** (`backend/app/api/anomalies.py:291-298`) | **KT, AÇK** |
| 10 | `backend/app/services/negotiation/boardroom.py:48` | Yönetim kurulu tartışması | kullanıcının serbest `topic` ve `context` metni (`backend/app/api/negotiation.py:268-271`) | **SOR** |
| 11 | `backend/app/agents/ceo/swot_agent.py:380` | SWOT özeti | **şirket adı** + türetilmiş maddeler | şirket adı |
| 12 | `backend/app/agents/compliance/orchestrator.py:333` | Uyum anlatısı | **şirket adı** + sayımlar | şirket adı |
| 13 | `backend/app/agents/anomaly_agent.py:426` | Anomali özeti | 8 anomali `başlık: açıklama` (satıcı adı içerir, `:120-122`, `:232-235`) | **KT** |
| 14 | `backend/app/agents/risk/orchestrator.py:234` | Risk anlatısı | yüklenen risk kaydından başlık `[:60]` (`:125`) | serbest metin |
| 24 | `backend/app/scheduler.py:474` | Sabah özeti | toplu göstergeler + uyarı mesajları (`:454-472`) | TOP + uyarı metni |
| E1–E3 | `backend/app/services/rag_service.py:144` ← `backend/app/worker.py:552`, `:730`, `:756` | Gömme (embedding) | belgenin tüm ham metni, 1800 karakterlik parçalar, 80.000 karaktere kadar (`backend/app/worker.py:541-547`, `:735`) | **HAM** |
| E5 | `backend/app/services/rag/retriever.py:138` | Soru gömme (yalnız Postgres) | kullanıcının sorusu | **SOR** |

**Yalnız toplu tutar/oran gönderen çağrılar (kişisel veri beklenmez):**
`backend/app/agents/ceo/strategic_priorities_agent.py:169`, `backend/app/agents/ceo/okr_agent.py:445`,
`backend/app/agents/audit/orchestrator.py:344`, `backend/app/agents/budget_agent.py:186`,
`backend/app/agents/tax_agent.py:310`, `backend/app/agents/multi_period_agent.py:203`,
`backend/app/services/llm_structured.py:503`, `:550`, `:588` (P&L, nakit, tahmin anlatıları),
`backend/app/agents/chro/attrition_agent.py:245` (departman/seviye düzeyinde, çalışan adı yok),
`backend/app/agents/chro/orchestrator.py:183`, `backend/app/agents/cmo/*` (`campaign_agent.py:298`,
`cohort_agent.py:270`, `funnel_agent.py:284`, `orchestrator.py:171`), `backend/app/agents/coo/*`
(`orchestrator.py:188`, `process_agent.py:421`, `resource_agent.py:270`, `sla_agent.py:531`),
`backend/app/agents/cto/*` (`incident_agent.py:250`, `infra_agent.py:222`,
`tech_debt_agent.py:168` — dosya yolları, yazar adı yok, `velocity_agent.py:228`, `orchestrator.py:224`).

**Not:** `backend/app/services/llm_router.py:202-228` gateway kaydını atlayarak çağrı yapar;
tek çağıranı bugün bir parametre hatası yüzünden istek göndermeden düşer
(`backend/app/services/reasoning_loop.py:288`). Hata düzeltilirse soru + toplu KPI gider.

### 4.3 Sonuç

Kişisel veri olarak yurt dışına çıkabilen alanlar: **karşı taraf/satıcı adı**
(`transactions.vendor`, `transactions.counterparty`, `canonical_transactions.counterparty`),
**işlem açıklaması** (`transactions.description`, `canonical_transactions.description`),
**yüklenen belgenin ham metni** (VKN/TCKN, IBAN, kişi adı içerebilir), **şirket adı**
(şahıs şirketinde kişi adı), **kullanıcının serbest metin soruları ve sohbet geçmişi**.
Kullanıcı adı-soyadı, e-postası, IP'si ve parola **gitmez**.

## 5. Veritabanı dışı depolar ve dış alıcılar

| Depo / alıcı | Ne var | Nerede | Saklama (bugün) | Yurt dışı? |
|---|---|---|---|---|
| `uploads/` dosya deposu | yüklenen ham dosya (PDF, XLSX, CSV, XML) `uploads/{job_id}/` (`backend/app/services/upload_service.py:129-133`), kök `./uploads` (`backend/app/config.py:210`) | TR sunucu | **Süresiz.** Yalnız veri kaynağı tek tek silinirse dosya silinir (`backend/app/api/datasource.py:265`) | Hayır |
| Redis — sohbet geçmişi | `conv:{user_id}:{session_id}` soru/yanıt turları (`backend/app/services/conversation_memory.py:18`; yazma `backend/app/api/chat.py:701-707`) | TR sunucu | 7 gün, kayan (`backend/app/services/conversation_memory.py:139`) | Hayır (ama içerik sonraki istemde LLM'e geri gider, §4 #5) |
| Redis — şirket bağlamı | şirket bağlam önbelleği (`backend/app/services/company_context.py:43`) | TR sunucu | 30 dk | Hayır |
| Uygulama logları | stdout/stderr (`backend/app/services/telemetry.py:419`); log mesajları karşı taraf adı içerebilir | TR sunucu / docker log | Docker log sürücüsüne bağlı — **tanımsız** | Hayır |
| OpenTelemetry | span'lerde yalnız görev, model, org kimliği (`backend/app/platform/model_gateway.py:398-405`) | `OTEL_ENDPOINT` (varsayılan localhost) | — | Yapılandırmaya bağlı |
| Sentry | `send_default_pii=False` (`backend/app/services/sentry_monitoring.py:70`), anahtar bazlı maskeleme (`:95-108`) | Sentry SaaS | — | **Bugün fiilen kapalı:** `sentry_dsn` okunur (`backend/app/services/sentry_monitoring.py:36`) ama `Settings`'te böyle bir alan yok ve fazla değişkenler yok sayılır (`backend/app/config.py:42`). Açılırsa yurt dışı |
| E-posta (SMTP) | uyarı özeti + org adı, alıcı adresleri (`backend/app/services/notification_service.py:245-270`; `backend/app/services/integrations.py:429`) | varsayılan `smtp.gmail.com` (`backend/app/config.py:177`) | Sağlayıcıya bağlı | **Evet** (Gmail seçilirse) |
| Slack / Teams / özel webhook | uyarı mesajları (`backend/app/services/notification_service.py:200`, `backend/app/services/alert_dispatcher.py:109`, `:165`) | ABD | Sağlayıcıya bağlı | **Evet**, müşteri açarsa |
| WhatsApp (Meta), Twilio | alıcı telefon no + mesaj (`backend/app/services/notification_service.py:347-349`, `:378-380`) | ABD | Sağlayıcıya bağlı | **Evet**, müşteri açarsa |
| Paraşüt, GİB, banka API'leri, TCMB | veri *çekilir* (`backend/app/services/erp/parasut_connector.py:47-48`, `backend/app/services/gib_efatura.py:47-48`) | TR | — | Hayır |

**Giden e-posta kutusu (outbox):** kodda ayrı bir e-posta outbox tablosu yoktur; e-postalar
bildirim servisinden doğrudan SMTP ile gönderilir. `outbox` kelimesi yalnız e-Fatura
akışında geçer (`backend/app/api/efatura.py`, `backend/app/services/gib_efatura.py`).

## 6. Saklama ve silme — bugünkü durum

- **Otomatik silme işi yoktur.** Kodda saklama süresine bakan bir zamanlanmış görev bulunmadı
  (`retention|purge|cleanup` araması yalnız ilgisiz eşleşmeler verir).
- **Silme rotaları yalnız tekil nesneler içindir:** veri kaynağı
  (`backend/app/api/datasource.py:244`), üye (`backend/app/api/org.py:330`), davet
  (`backend/app/api/org.py:619`), ilişkili taraf (`backend/app/api/related_party.py:194`),
  SMMM müşterisi (`backend/app/api/smmm_benchmark.py:260`), sohbet oturumu
  (`backend/app/api/chat.py:794`), entegrasyon (`backend/app/api/erp_integrations.py:104`).
- **Yok:** kullanıcı hesabı silme, organizasyon silme, analiz işi (ve işlemleri) silme,
  karşı taraf adına göre arama/dökme/silme. KVKK m.11 başvurusu bugün koddan karşılanamaz
  (acik-konular §4).
- Önerilen süreler: acik-konular §2.

## 7. Özel durumlar

- **İK verisi:** CHRO hattı (`backend/app/agents/chro/`) maaş ve işe giriş verisini işler;
  LLM'e yalnız departman/seviye düzeyinde toplu gider (`backend/app/agents/chro/attrition_agent.py:245`).
  Yüklenen İK dosyası ise `uploads/`'ta ham hâliyle durur. acik-konular §6.
- **Özel nitelikli veri (m.6):** amaçlanmaz, ama serbest metinli banka açıklamalarında
  (ör. hastane, sendika ödemesi) bulunabilir; ayırt eden bir mekanizma yoktur.
