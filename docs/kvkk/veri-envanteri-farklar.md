# PR #68 belgeleriyle farklar (sahip için)

PR #68 (`docs/kvkk-document-set`) sahibindir ve düzenlenmedi. Üretilmiş harita
([veri-envanteri-uretilen.md](veri-envanteri-uretilen.md)) kod şemasından çıkar; aşağıdakiler iki belgenin ayrıştığı yerlerdir.
#68 `master @ 61747c8`'den yazıldı; bu iş sonraki master'dan (`e5b0622`) çıkarıldı.

## Tablolar

1. **64 tablodan 15'i #68'de satır olarak yok:** `cash_radar_snapshots`, `category_overrides`, `counterparty_aliases`,
   `decisions`, `direction_mappings`, `donem_kilitleri`, `email_verification_tokens`, `held_transactions`,
   `journal_entries`, `journal_lines`, `org_erasure_records`, `org_erasure_requests`, `outbox_messages`,
   `password_reset_tokens`, `payment_plan_changes`. Özellikle **`outbox_messages`** (alıcı e-posta, konu, gövde; SMTP,
   Slack, WhatsApp'a giden her şey; webhook gövdesi bir URL taşır), `journal_*` (açıklama serbest metni) ve `decisions`
   (kim karar verdi) kişisel veri taşır.
2. **#68'de olup artık olmayan tablo:** `sync_audit_logs`. Master'da böyle bir tablo yok.
3. **Veritabanı dışı depo, #68'de yok:** `agent_memory_episodes` (PostgreSQL) / `agent_memory` (SQLite): her ajan
   çalışmasının özeti ve anlatısı, ORM'de tanımlı olmadığı için şemadan da görünmez. Bu iş silmeye ekledi.
4. **Redis anahtarları:** #68 yalnız `conv:` ve `company_context:` sayıyor. Ayrıca `semantic:`, `morning_brief:`,
   `monday_briefing:`, `temporal:`, analitik önbelleği, `ceo:<job>`, `ack:<job>:*` var; hepsi silmeye eklendi.

## İddialar

5. **"Silme/dışa aktarma işlevi yok" (acik-konular §4, aydınlatma taslağındaki mühendis notu):** bugün **şirketin tamamı**
   için iki adımlı silme var (`org_erasure`, PR'dan önce de) ve bu iş **kişi** silmeyi, soğuma süresini, iptali ve
   operatör yolunu ekledi. Kişi bazlı **dışa aktarma** (`GET /privacy/my-data`) ve şirket dışa aktarımı (owner, iş olarak, süreli indirme) eklendi. Karşı taraf adına göre arama/silme hâlâ yok (Q9).
6. **Saklama:** #68 "hiçbir tabloda otomatik silme yok" diyor; saklama işi artık var ama varsayılan olarak çoğu kalem için yalnız sayar (`RETENTION_DRY_RUN=true`): bu kalemlerin süreleri operatör ilk raporu okuyup bayrağı kapatana kadar **yürürlükte değildir** (üretimde ön kontrol uyarısı `retention_dry_run`). LangGraph durum kayıtları ve silinmiş şirket artıkları bayraktan bağımsız silinir. Hangi kalemin hangisi olduğu üretilmiş haritada ("Retention: in effect or not"). Kodda ise `RETENTION_POLICY`
   (compliance_gdpr.py) farklı sayılar yazıyor (işlemler 2 yıl, denetim kaydı 5 yıl) ve `/compliance/retention-report`
   bunları "politika" diye gösteriyor; #68 ise denetim kaydı için 2 yıl öneriyor. Üç kaynak birbirinden farklı: hukukçu karar vermeden
   hiçbiri defter tablolarına uygulanmadı; sabit sayılar kaldırıldı, `/compliance/retention-report` artık gerçek değerleri söyler (Q2, Q5).
7. **`users`: "hesap kapanınca +90 gün" (#68):** üye silme şimdi soğuma süresi (7 gün) sonunda hemen takma adlandırır; +90 gün beklemez. Hangisi doğru (Q4, Q11)?
8. **Aydınlatma taslağı "Şirket 30 gün içinde yanıtlar":** ürün artık 7 günlük iptal edilebilir bekleme sonrası siler; metin bunu söylemeli.
9. **#68 "kişi silme yok" ve eski `POST /compliance/erasure-request`:** bu uç master'da **her çağrıda 500 verirdi** (var olmayan alanlarla bildirim
   oluşturuyordu) ve isteyenin e-postasını ve gerekçesini bildirim yüküne yazacaktı. Kaldırıldı.
10. **LLM:** #68'in söylediği (maskeleme yok, varsayılan DeepSeek) master'da bugün de doğru; bu iş maskeleme **eklemedi**. Haritada `masked: false`
    olarak duruyor ve bir test, maskeleme eklenirse bu satırın güncellenmesini zorunlu kılıyor.
