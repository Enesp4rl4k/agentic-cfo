# Mimari karar kayıtları (ADR)

Her kayıt tek bir kararı yazar: bağlam, karar, sonuçları, düşünülen alternatifler ve kanıt. Kayıtlar silinmez; bir karar değişirse yeni bir kayıt eskisinin yerine geçer ve eskisinin durumu "yerini aldı: NNNN" olur.

**Durumlar:** *Önerildi* (yazıldı, uygulanmadı), *Kabul edildi* (uygulandı ya da uygulayan bir PR'da), *Yerini aldı*, *Reddedildi*.

**Kimin kararı:** geliştiricinin mi, sahibin mi (plan v11 §7). Sahip kararı gereken kayıt, sahip onaylayana kadar öyle işaretli kalır; plan v11 ilkesi gereği önerilen varsayılan uygulandıysa bu açıkça yazılır.

| # | Karar | Durum | Kimin | Plan v11 |
|---|---|---|---|---|
| [0001](0001-tek-defter-yevmiye-tablolari.md) | Tek defter: çift taraflı yevmiye tabloları | Önerildi | Geliştirici | K1, C3, A1.1–A3.1 |
| [0002](0002-karar-gunlugu-eklemeli.md) | Karar günlüğü eklemeli; tam olay kaynaklama yok | Önerildi | Geliştirici | K2, C4, A1.6–A2.2 |
| [0003](0003-dis-etkiler-outbox.md) | Dış etkiler outbox'tan, bir kez | Kabul edildi (#56) | Geliştirici | K3, C9, A0.5 |
| [0004](0004-model-saglayicilari.md) | Model sağlayıcıları gateway arkasında, seçim ölçümle | Önerildi | Sahip | K4, C7 |
| [0005](0005-langgraph-yukseltmesi.md) | LangGraph yükseltmesi: önce yüzeyi küçült | Önerildi | Geliştirici | K5, C6, A3.3 |
| [0006](0006-rol-ajanlari.md) | Rol ajanları kanıt olmadan pilot yoluna dönmez | Önerildi | Sahip | K6, C6, A3.5 |
| [0007](0007-mimari-kurallar-ratchet.md) | Mimari kurallar küçülen listelerle (ratchet) testte | Kabul edildi (#54) | Geliştirici | §8, A0.8 |
| [0008](0008-musavir-onayi-bulten-epostasi.md) | Müşavirli şirkette bülten e-postası onay bekler | Kabul edildi, varsayılan (#56) | Sahip | K10 |

Yeni kayıt: sıradaki numarayla `NNNN-kisa-ad.md`, şu bölümlerle: **Durum**, **Bağlam**, **Karar**, **Sonuçlar**, **Alternatifler**, **Kanıt**.
