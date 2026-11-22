# Yedekler ve silme: ifade ve yordam

## Müşteriye söylenecek ifade (taslak, hukukçu onayı gerekir)

> Silme talebiniz yerine getirildiğinde verileriniz canlı sistemden silinir veya (defter kayıtları için)
> kişisel alanlardan arındırılır. Yedeklerimiz geriye dönük olarak değiştirilemez; silinen veri, yedek
> dönemi (bugünkü yapılandırmada en çok 14 gün) dolana kadar yedeklerde kalabilir ve süre dolunca yedekle birlikte yok olur.
> Bir yedek geri yüklenirse, silme kaydındaki şirketler ve kişiler geri yüklemenin hemen ardından yeniden silinir.

## Yordam

1. Geri yüklemeden **önce** silinenleri dışa aktarın (kişisel veri içermeyen özetler):
   `python scripts/reapply_erasures.py --export > erased.json`. Dosyayı veritabanının dışında saklayın.
2. Geri yükleyin ([db-restore.md](../ops/runbooks/db-restore.md)).
3. `python scripts/reapply_erasures.py --apply erased.json`: geri gelen şirketler ve kişiler yeniden silinir (idempotent).
4. Eski bir yedeği **elle düzenlemeyin**.

Kod: `app/services/privacy/erasure_flow.py:reapply_erased`; test: `tests/test_privacy_breach_and_restore.py`.
Silme kaydı yalnız özet (hash) içerir; ham şirket veya kişi kimliği tutulmaz, bu yüzden liste kimlikleri değil karşılaştırılan hash'leri taşır.

## Doğrulanmadı

Gerçek bir yedekle denenmedi (yedek betikleri PR #96'da, birleşmedi). Mantık SQLite fikstüründe test edildi.
