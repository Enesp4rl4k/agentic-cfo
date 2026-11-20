# KVKK — Sahibin karar vermesi gereken açık konular

> Pilot öncesi bu kararlar verilmeden aydınlatma metni ve veri işleme sözleşmesi
> kesinleştirilemez. Her madde için mühendisin önerisi var; karar sahibin ve avukatındır.
> Teknik dayanaklar: [veri-envanteri.md](veri-envanteri.md).

## 1. LLM'e giden veri — yurt dışı aktarım (en önemli konu)

**Durum.** Sunucular Türkiye'de olsa da, LLM çağrıları Türkiye dışına gider:

- Varsayılan sağlayıcı **DeepSeek (Çin)**dir, OpenAI değil:
  `backend/app/config.py:213` (`llm_model = "deepseek-chat"`) ve
  `backend/app/config.py:218` (`llm_base_url = "https://api.deepseek.com"`); `.env.example:11-12`
  de aynı değerleri verir. OpenAI'ye geçmek yalnızca bir ortam değişkeni değişikliğidir
  (`.env.example:14-15`). Staging/prod'da hangisinin ayarlı olduğu bu belgeden bilinemez —
  **önce bunu netleştirin.** Ayrıca gateway yalnız `gpt-*` model adları gönderir
  (`backend/app/platform/model_catalog.py:60-65`), yani varsayılan ayar tutarsızdır.
  Metin gömme (embedding) de aynı adrese gider (`backend/app/services/rag_service.py:131-147`).
- İsteme girebilen alanlar veri-envanteri §4'te tek tek listelidir. Kısaca: karşı taraf
  adları (gerçek kişi olabilir), banka/fatura açıklama metinleri, yüklenen belgenin ham
  metni, kullanıcının serbest metin soruları. Gönderimden önce maskeleme **yoktur**.
- Çin, KVKK m.9 bakımından yeterlilik kararı olan bir ülke değildir; ABD de değildir.

**Seçenekler.**

| Seçenek | Hukuki yük | Mühendislik yükü | Ürüne etkisi |
|---|---|---|---|
| A. Açık rıza (m.9/7'deki istisnai durumlar) | Rıza her ilgili kişiden alınmalı; *karşı taraflardan* (faturadaki müşteri/tedarikçi) rıza almak fiilen mümkün değil | Düşük | Rıza vermeyen kullanıcıda LLM özellikleri kapanmalı |
| B. Uygun güvence: Kurul'un standart sözleşmesi + 5 iş günü içinde Kurul'a bildirim (m.9/4) | Sağlayıcının standart sözleşmeyi imzalaması gerekir; DeepSeek'in imzalaması belirsiz, OpenAI için de teyit gerekir | Düşük | Yok |
| C. **Maskeleme / takma ad** — isteme girmeden önce ad, VKN/TCKN, IBAN, e-posta, telefon yer tutucuyla değiştirilir, cevap dönünce geri yerleştirilir | Maskeleme gerçekten kişiyi belirlenemez kılarsa aktarım kişisel veri aktarımı olmaktan çıkar; serbest metinde %100 garanti yoktur | Orta: model gateway tek giriş noktası olduğundan (veri-envanteri §4.1) tek yerde yapılabilir | Karşı taraf bazlı yorumlar ("X firmasından tahsilat gecikiyor") yer tutucu üzerinden çalışır |
| D. Türkiye'de / AB'de barındırılan model (TR bulutunda açık ağırlıklı model veya AB bölgeli bir sağlayıcı) | TR: aktarım yok. AB: yine m.9 kapsamı, ama sözleşme imzalatmak daha olası | Yüksek (barındırma, kalite ölçümü) | Kalite eval ile doğrulanmalı |
| E. LLM'siz çalışma | Yok | Kod zaten anahtarsız modda deterministik çalışmayı destekliyor (veri-envanteri §4.1) | Açıklama metinleri ve sohbet kaybolur |

**Öneri.** Pilot için **C + B**: gateway'de maskeleme (ad, VKN/TCKN, IBAN, e-posta, telefon,
ham belge metni hiç gönderilmez), ek olarak sağlayıcıyla standart sözleşme. Sağlayıcı olarak
DeepSeek yerine standart sözleşmeyi imzalayabilecek bir sağlayıcı. Uzun vadede D.

**Karar gereken:** sağlayıcı, seçenek, ve maskeleme yapılana kadar pilotun LLM'siz (E)
mi açılacağı.

## 2. Saklama süreleri

**Durum.** Kodda hiçbir tablo için otomatik silme yok (veri-envanteri §6). Yüklenen dosyalar
diskte süresiz kalır; yalnızca kullanıcı bir veri kaynağını tek tek silerse dosya silinir
(`backend/app/api/datasource.py:265`). Redis'te sohbet geçmişi 7 gün
(`backend/app/services/conversation_memory.py:139`), şirket bağlamı 30 dk
(`backend/app/services/company_context.py:43`) tutulur.

**Öneri (veri-envanteri §5'teki tablo):**

| Veri | Önerilen süre | Gerekçe |
|---|---|---|
| Muhasebe kaynaklı kayıtlar (işlemler, açık kalemler, raporlar, SMMM onayları) | Hesap yılı sonundan itibaren 5 yıl, sonra sil/anonimleştir | VUK m.253; TTK m.82 10 yıl der — **avukat hangisinin şirketin değil Platform'un yükümlülüğü olduğunu söylemeli**. Asıl defter şirkette ve SMMM'dedir; Platform kopyadır |
| Yüklenen ham dosyalar (`uploads/`) | İşlendikten sonra `[90]` gün | Kayıtlar zaten tabloya çıkarılıyor; ham dosya yalnızca yeniden işleme için |
| `transactions.raw_text`, `rag_chunks.chunk_text` (belgenin ham metni) | Ham dosya ile aynı | Ham dosyanın kopyasıdır |
| Denetim kaydı (`audit_logs`, IP dahil) | `[2]` yıl | Güvenlik olayı incelemesi |
| `llm_call_logs`, `agent_runs`, `agent_jobs` / `analysis_jobs` iş kayıtları | `[1]` yıl | İşletim |
| Bildirimler, uyarılar | `[1]` yıl | |
| Kullanıcı hesabı | Hesap kapandıktan `[90]` gün sonra | |
| Redis sohbet geçmişi | 7 gün (mevcut) | |

**Karar gereken:** süreler ve silme mi anonimleştirme mi.

## 3. VERBİS kaydı

- **Platform için:** Platform veri işleyen olduğu ölçüde VERBİS kaydı veri sorumlusunun
  yükümlülüğüdür. Ancak Platform'un kendi veri sorumlusu olduğu veriler de vardır (§5).
  Kayıt istisnası (yıllık çalışan < 50 ve mali bilanço < 100 milyon TL, ana faaliyeti özel
  nitelikli veri işleme olmayan) için Platform'u işleten şirketin durumu kontrol edilmeli.
- **Müşteri şirketler için:** Aile şirketlerinin çoğu eşik altında olabilir; ancak bu kendi
  yükümlülükleridir. Platform, VERBİS'e girilecek bilgiyi (kategori, amaç, alıcı, yurt dışı)
  veri-envanteri'nden hazır bir ek olarak verebilir.

**Karar gereken:** Platform şirketinin VERBİS durumu; müşterilere hazır VERBİS eki verilip
verilmeyeceği.

## 4. İlgili kişi başvuruları (m.11) — erişim / silme işlevi yok

Kodda kişi bazlı dışa aktarma veya silme yok; ne kullanıcı hesabı silme, ne organizasyon
silme rotası var (yalnızca tek tek kaynak/üye/davet silme: `backend/app/api/datasource.py:244`,
`backend/app/api/org.py:330`). Karşı taraf adına göre arama/silme hiç yok.

**Karar gereken:** pilotta elle yürütülen bir prosedür mü (SQL yasak — ORM ile bir yönetim
komutu yazılmalı), yoksa ürüne bir "veri dökümü / sil" ekranı mı.

## 5. Platform'un kendi veri sorumlusu olduğu veriler

`users`, `pilot_invites`, `user_feedback`, `smmm_muhasebeci`, `organizations.stripe_*` için
Platform doğrudan veri sorumlusudur (hesap açma, faturalama, pazarlama-dışı iletişim).
Ayrı bir aydınlatma metni ve kayıt/üyelik sözleşmesine ek gerekir.

**Karar gereken:** Platform'u işleten tüzel kişi kim; metni avukat mı yazacak.

## 6. İK verisi (çalışan maaşları vb.)

Kodda bir İK analiz hattı var (`backend/app/agents/chro/`): maaş, işe giriş tarihi gibi
çalışan verisi yüklenirse işlenir ve LLM'e gidebilir. Bu, karşı taraf verisinden daha
hassastır ve aile şirketlerinde ad-soyadla gelir. Pilot kapsamı "Pazartesi nakit cevabı" ise
(PLAN_V10) bu hat pilotta kapalı tutulabilir.

**Karar gereken:** İK yüklemesi pilotta kapalı mı.

## 7. Diğer yurt dışı alıcılar

- **SMTP:** varsayılan `smtp.gmail.com` (`backend/app/config.py:177`). TR'de bir SMTP
  sağlayıcısı seçilirse aktarım ortadan kalkar; e-posta içeriğinde uyarı metni (karşı taraf
  adı içerebilir) gider.
- **Sentry:** bugün fiilen kapalı — `sentry_dsn` okunuyor
  (`backend/app/services/sentry_monitoring.py:36`) ama `Settings`'te bu alan yok
  (`backend/app/config.py:42`). Biri "düzeltip" açarsa: `send_default_pii=False`
  (`backend/app/services/sentry_monitoring.py:70`) ve anahtar bazlı maskeleme (`:95-108`)
  var, ama ERROR seviyesindeki log mesajları da gönderilir (`:60-63`) ve log mesajları karşı
  taraf adı içerebilir. Seçenek: kapalı tutmak veya self-hosted (TR) çalıştırmak.
- **Slack / WhatsApp:** yalnızca müşteri açarsa; aydınlatma metninde belirtilmeli.

**Karar gereken:** SMTP sağlayıcısı; Sentry SaaS mı, self-hosted mı, kapalı mı.

## 8. Mali müşavirin hukuki konumu

Bkz. veri-isleme-sozlesmesi-taslak §1.1. SMMM şirketin veri işleyeni mi, bağımsız veri
sorumlusu mu? Sözleşme kurgusu buna göre değişir.

**Karar gereken:** avukatla birlikte.
