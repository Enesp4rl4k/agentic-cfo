# 0003 · Dış etkiler outbox'tan, bir kez

- **Durum:** Kabul edildi (#56, 2026-11-14)
- **Kimin:** Geliştirici
- **Plan v11:** K3, C9; A0.5 (ilk tüketici: pazartesi bülteni e-postası), A2.6 (bildirimler, webhook), A5.1 (kaos testleri)

## Bağlam
E-posta, bildirim, Slack/WhatsApp ve webhook gibi dış etkiler iş kodunun içinden doğrudan gönderiliyordu. Tekrar koruması yoktu ve SMTP ayarı yoksa e-posta sessizce atlanıyordu (`notification_service._send_email`). Pilot bülteni iki kez gitse ya da hiç gitmese kimse bilmezdi.

## Karar
İş kodu dış etkiyi göndermez; `outbox_messages` tablosuna, ne için olduğunu söyleyen benzersiz bir anahtarla bir satır yazar (ör. `monday_briefing:{org}:{briefing_id}:{alıcı}`). Aynı anahtarla ikinci yazım yeni bir şey yazmaz. Tek bir gönderici bekleyen satırları gönderir ve sonucu satıra yazar: `sent`, gerekçeli `failed` ya da 5 denemeye kadar yeniden deneme. Bir insanın onayını bekleyen mesaj `held` durumundadır.

**Gönderici arq işi değil, zamanlayıcı işidir** (`outbox_delivery`, 5 dakikada bir, Redis kilidiyle tek süreçte). Plan v11 K3 arq işi öneriyordu. Uygulamada zamanlayıcı seçildi, çünkü arq worker'ı bu geliştirme ortamında koşmuyor (Docker ve Redis yok) ve zamanlayıcının çoklu süreç kilidi (`scheduler._exclusive`) zaten var.

## Sonuçlar
- Her dış etki bir kez olur; olmayan etki gerekçesiyle görünür (`GET /briefing/monday/deliveries`).
- SMTP istemcisini yalnız teslim servisi içe aktarır; uygunluk testi F3 bunu zorlar.
- Etkinin kendisi ile iş mantığı ayrı test edilir.
- Bekleyen bir mesaj en fazla 5 dakika gecikir; pazartesi gönderimi bu gecikmeyi beklemeden aynı koşuda teslim eder.

## Alternatifler
- **İş kodunda doğrudan gönderim artı "gönderildi" bayrağı:** gönderim ile bayrak arasında bir çökme mesajı iki kez gönderir ya da hiç göndermez. Reddedildi.
- **Ayrı mesaj kuyruğu (Kafka vb.):** tek süreçli bu sistem için gereksiz altyapı (plan v11 §3.2). Reddedildi.

## Kanıt
`backend/app/models/outbox_message.py`, `backend/app/services/outbox.py`, `backend/app/services/briefing_delivery.py`, `backend/tests/test_briefing_outbox.py` (#56).
