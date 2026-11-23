# Veri yaşam döngüsü: mühendislik notları

Hukuki görüş değildir; sorular [avukata-sorular.md](avukata-sorular.md)'de, her biri için seçilen muhafazakâr varsayılanla.

## Neler var, nerede

| İş | Kod | Test |
|---|---|---|
| **Kişisel veri haritası** (kayıt defteri): her tablo/sütun, kimin verisi, amaç, kategori, saklama sınıfı, üçüncü taraf akışı; dosya, Redis, ajan belleği, log, yedek depoları | `app/services/privacy/registry*.py`; üretilen belge `docs/kvkk/veri-envanteri-uretilen.md` (`python -m app.services.privacy.inventory_doc`) | `test_privacy_registry.py`: yeni tablo veya kişisel görünen sütun (email, phone, iban, tckn, vkn, name, address, ip, ...) kayıtsız eklenirse **adıyla** düşer; üretilen belge bayatsa düşer |
| **Şirket silme**: iki adım, soğuma süresi, iptal, operatör yolu, karar kaydı, zamanlanmış yürütücü | `api/org_erasure.py`, `services/privacy/erasure_flow.py`, `services/org_erasure.py` | `test_org_erasure.py`, `test_erasure_flow.py` |
| **Silmenin uçtan uca ispatı**: DB satırları (şemadan türetilen kapsam), diskteki dosyalar, Redis, süreç içi yedekler, ajan belleği | `services/privacy/ephemeral.py` | `test_erasure_end_to_end.py` (komşu şirketin kopyaları yerinde kalır) |
| **Üye silme** (şirket kalır, takma adlı tutma) | `api/member_erasure.py`, `services/privacy/member_erasure.py` | `test_erasure_flow.py` |
| **Yedekten dönüşte yeniden silme** | `erasure_flow.reapply_erased`, `scripts/reapply_erasures.py` | `test_privacy_breach_and_restore.py` |
| **Şirket dışa aktarımı** (owner; ZIP, belgelenmiş JSONL + manifest; iş olarak; boyut sınırlı; süreli kimlik doğrulamalı indirme; karar kaydı) ve **üyenin kendi dışa aktarımı** | `services/privacy/export_bundle.py`, `export_flow.py`, `api/privacy_data.py` | `test_privacy_export.py` |
| **Saklama**: ayarlanabilir, muhafazakâr, idempotent, önce rapor (dry-run), tek şirkete bağlı; defter hiç silinmez | `services/privacy/retention.py`, `jobs.py` | `test_privacy_retention.py` |
| **Bildirim/aydınlatma sürümü kabulü** (sürüm değişince yeniden sorulur; kabul yalnız Ayarlar > Veri ve gizlilik ekranında kaydedilir, girişten sonra zorunlu istem yok) | `services/privacy/notices.py` | `test_privacy_retention.py` |
| **Veri ve gizlilik ekranı** | `frontend/src/components/privacy/`, `/settings/privacy` | `privacy-settings.test.tsx` |
| **İhlal kapsamı** (hangi şirketler, hangi kategoriler) | `services/privacy/breach_scope.py`, `GET /privacy/operator/breach-scope` | aynı dosya; runbook `docs/ops/runbooks/data-breach.md` |

## Silmede bulunan ve kapatılan açıklar

1. **Ajan belleği** (`agent_memory_episodes` / `agent_memory`) ORM şemasında olmadığı için şirket silmede hiç görünmüyordu: her çalışmanın özeti
   ve anlatısı kalıyordu. Artık siliniyor.
2. **Redis**: sohbet geçmişi (`conv:<kullanıcı>:*`, 7 gün), şirket bağlamı, semantik anlık görüntüler, sabah/pazartesi özeti, zamansal olaylar, analitik önbelleği,
   `ceo:<job>`, `ack:<job>:*` ve süreç içi yedekleri silinmiyordu. Artık siliniyor; Redis kapalıysa kayıt `redis_failed` der (süre dolunca kendiliğinden gider).
3. **Üçüncü taraf kopyalar** (Stripe müşterisi, ERP/bağlayıcı yetkileri) sessizce kalıyordu: kayıt artık sayısını söyler (`_external_followup`).
4. **Anında geri dönüşsüzlük**: onay hemen siliyordu; artık soğuma süresi ve iptal var.
5. **Bozuk uç**: `POST /compliance/erasure-request` her çağrıda 500 veriyordu ve e-posta ile gerekçeyi bildirim yüküne yazacaktı; kaldırıldı.

Silinemeyenler (belgelendi, [yedek-ve-silme.md](yedek-ve-silme.md) ve harita `stores`): LLM sağlayıcısının kendi tuttuğu istemler, uygulama günlükleri, Sentry (kapalı), yedekler.

## Yeni bir tablo eklerken

1. `app/services/privacy/registry_tables.py`'e satır ekleyin (kişisel veri yoksa `NO_PERSONAL_DATA`'ya gerekçeyle).
2. Tablo `org_id` taşıyorsa silme onu kendiliğinden kapsar; defterde **tutulacaksa** `org_erasure.RETAINED`'a kişisel sütunları `scrub` olarak yazın (test kayıt defteriyle çapraz kontrol eder).
3. `python -m app.services.privacy.inventory_doc` ile belgeyi yeniden üretin.
