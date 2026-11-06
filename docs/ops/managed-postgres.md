# Yönetilen Postgres: kurulum ve yedek runbook'u

*Plan v10 §O1. Pilot şirketlerin finans verisi küme içindeki bir pod'da (10–20 Gi disk, yedeksiz) durmaz; yönetilen bir Postgres'e gider. Bu belge hangi sağlayıcı seçilirse seçilsin geçerli olan adımları yazar. Sağlayıcıya özgü komutlar sağlayıcı seçilince eklenir.*

## 1. Sağlayıcıda aranacaklar

| Gereksinim | Neden |
|---|---|
| PostgreSQL 16 | `pgvector/pgvector:pg16` ile geliştirildi ve CI'da bu sürümle denendi. |
| `pgvector` eklentisi | Migration 023 (`RagChunk.embedding`) eklenti yoksa kasıtlı olarak hata verir. |
| Zorunlu TLS | Uygulama `POSTGRES_SSLMODE=require` ile bağlanır; `verify-full` için sağlayıcının CA sertifikası gerekir. |
| Günlük yedek, en az 7 gün, ve zamana göre geri dönüş (PITR) | Yedeksiz tek kopya, bu planın kapattığı risktir. |
| Veri konumu | KVKK: verinin tutulduğu ülke hukukçu tarafından onaylanmalı (§7 karar 4). |
| Özel ağ ya da IP kısıtı | Veritabanı internete açık olmamalı; yalnız kümenin çıkış adresi bağlanabilmeli. |
| Uygulamaya özel kullanıcı | Süper kullanıcı ile bağlanılmaz. |

## 2. Bağlanmak

`POSTGRES_PASSWORD` her zaman `aicfo-secrets` içinden gelir; ayar dosyalarına yazılmaz.

**Kustomize:** `k8s-overlays/managed-postgres/kustomization.yaml` içinde `POSTGRES_HOST` değerini düzenleyin, sonra:

```bash
kubectl apply -k k8s-overlays/managed-postgres
```

Bindirme küme içi Postgres'i çıkarır ve `POSTGRES_SSLMODE=require` ekler. Host düzenlenmezse `.invalid` uzantılı sahte bir adresle bağlanmaya çalışır: yanlış bir veritabanına değil, hiçbir yere gitmez.

**Helm:**

```bash
helm install aicfo helm/agentic-cfo -f helm/agentic-cfo/values-managed-postgres.yaml \
  --set postgres.external.host=<örnek-host> --set secrets.postgresPassword=<parola>
```

Host verilmezse şablon açık bir hata verir.

Tek URL ile bağlanmak isterseniz `DATABASE_URL_OVERRIDE` kullanılır. TLS parametresini `ssl=` ya da `sslmode=` diye yazabilirsiniz; uygulama her sürücü için doğru yazımı üretir.

## 3. İlk kurulum

1. Sağlayıcının yönetici hesabıyla bir kez: `CREATE EXTENSION IF NOT EXISTS vector;` (uygulama kullanıcısının buna yetkisi olmayabilir).
2. Migrasyon işi çalışır (`alembic upgrade head`); işin günlüğü bitişi gösterir.
3. `BACKEND_URL=<adres> ./scripts/staging-smoke.sh` çıkış kodu 0 olmalı.
4. Worker'ın gerçek ortamda ilk koşusu: bir demo hesabıyla örnek bir banka ekstresi yükleyip `/runs` kaydının `completed` olduğunu görün.

## 4. Yedek ve geri yükleme tatbikatı

**Tatbikat yapılmamış yedek, yedek sayılmaz.** Pilot başlamadan önce bir kez, sonra ayda bir:

1. Sağlayıcıda canlı örneğin son yedeğinden (ya da bir PITR noktasından) **yeni bir örnek** geri yükleyin. Canlının üstüne yazılmaz.
2. Yeni örneğe `POSTGRES_HOST`'u çeviren ayrı bir staging dağıtımı bağlayın.
3. Karşılaştırın: `organizations`, `analysis_jobs`, `canonical_transactions` ve `open_items` satır sayıları, ve `ledger_summary` çıktısı canlıyla aynı olmalı.
4. Geri yükleme için geçen süreyi (RTO) ve kaybedilen en yeni işlemin yaşını (RPO) bu belgeye tarihle yazın.
5. Geri yüklenen örneği silin.

| Tarih | Kaynak yedek | RTO | RPO | Satır sayıları tuttu mu |
|---|---|---|---|---|
| *(ilk tatbikat bekleniyor)* | | | | |

## 5. Denenmemiş olanlar

- Bu dosyalar bir kümede ve gerçek bir yönetilen veritabanında hiç koşmadı. Bu makinede Docker, Postgres ve Redis yok; kustomize çıktısı `kubectl kustomize` ile, bağlantı adresleri testlerle doğrulandı.
- `verify-full` için CA sertifikasının pod'a nasıl bağlanacağı sağlayıcı seçilince belirlenir.
- Bağlantı havuzu sınırları (`max_connections`) sağlayıcının planına göre ayarlanmalı; backend ve worker kopya sayısı bu sınırı aşmamalı.
