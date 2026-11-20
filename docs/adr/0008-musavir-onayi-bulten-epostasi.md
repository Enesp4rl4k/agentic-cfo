# 0008 · Müşavirli şirkette bülten e-postası onay bekler

- **Durum:** Kabul edildi, önerilen varsayılan olarak (#56, 2026-11-14); sahip onayı bekliyor
- **Kimin:** Sahip
- **Plan v11:** K10; SMMM planı değişmezi D5

## Bağlam
SMMM planının değişmezi: patrona giden hiçbir şey müşavirin onayından geçmeden gitmez (D5). Pazartesi bülteni radarın rakamlarından yazılır; radar, müşavirin henüz onaylamadığı kayıtları da görebilir. Sahip "benden bekleme, sırayla devam et" dedi; bu yüzden plan v11'in önerdiği varsayılan uygulandı ve burada açıkça yazıldı.

## Karar
Şirkette bir müşavir üyeliği (`smmm`) varsa bülten e-postası outbox'ta `held` durumunda bekler; yalnız o şirketin müşaviri `POST /briefing/monday/release` ile serbest bırakabilir (başkası için 403). Ekran (`/bulten`) beklemez; patron bülteni uygulamada her zaman görür.

## Sonuçlar
- Müşavirli şirkette e-postayla dışarı çıkan şey müşavirin onayından geçmiş olur.
- Müşavir serbest bırakmazsa e-posta gitmez; durum `GET /briefing/monday/deliveries`'te `awaiting_accountant_release` olarak görünür.
- Müşavirin serbest bırakma ekranı henüz yok, yalnız API var; müşavir portföyü (M4) ile gelir.

## Alternatifler
- **E-posta beklemesin:** D5 ile çelişir. Sahip bunu seçerse değişiklik tek satırdır (`briefing_delivery.enqueue_briefing_emails` içindeki `held` koşulu) ve bu kayıt "yerini aldı" olur.
- **Ekran da beklesin:** patron kendi şirketinin rakamını göremez; pilotun değeri düşer.

## Kanıt
`backend/app/services/briefing_delivery.py`, `backend/app/api/monday_briefing.py` (`release_briefing`), `backend/tests/test_briefing_outbox.py` (#56).
