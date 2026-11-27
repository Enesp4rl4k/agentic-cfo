# Runbook: tek VPS staging

*Kurulum: [staging.md](staging.md). Buradaki her komut sunucuda, `/opt/agentic-cfo` içinde, `deploy` kullanıcısıyla çalışır.*

```bash
alias dc='docker compose -f docker-compose.prod.yml'
```

## 1. Deploy

Sıralı kontrol listesi (ilk kurulum ve yükseltme): [staging.md §6](staging.md#6-deploy-kontrol-listesi). Aşağıdaki komut bloğu onun özetidir.

```bash
git fetch origin && git checkout <sha veya origin/master>
PREV=$(grep '^IMAGE_TAG=' .env | cut -d= -f2)      # geri alma için not edin
NEW=$(git rev-parse --short HEAD)
./scripts/backup.sh                                 # deploy öncesi yedek — atlamayın
./scripts/up-prod.sh                                 # IMAGE_TAG=$(git rev-parse --short HEAD) → build → migrate (alembic + preflight --db) → up -d → waits for healthy; logs of every service on failure
dc ps                                               # migrate "exited (0)", diğerleri healthy
./scripts/smoke-test.sh --api https://<API_DOMAIN> --app https://<APP_DOMAIN> --expect-commit "$NEW"
curl -fsS https://<API_DOMAIN>/api/v1/ready         # "status": "ready" (ilk 5 dk "degraded" olabilir)
```

- Bellek alt sınırı: `backend` en az **2560m**, `worker` en az **2g** (artı Postgres ve Redis); bunun altında yüklenen dosyaları ayrıştırırken `OOMKilled` görürsünüz ([staging.md §2](staging.md#2-sunucu), [parser-sizing.md](parser-sizing.md)).
- backend, worker ve worker-maintenance her başlangıçta `python -m app.core.preflight --db` çalıştırır: `FATAL` bulgu (şablon gizli, localhost bağlantıları, demo modu...) ya da head'de olmayan şema konteyneri **başlatmaz**; `dc logs <servis>` nedeni söyler.
- `migrate` sıfırdan farklı çıkarsa backend **başlamaz**, eski konteynerler çalışmaya devam eder: `dc logs migrate`.
- Eski imajlar etikettiyle diskte kalır (geri alma bunlara dayanır). Ayda bir: son 5 etiket dışındakileri `docker image rm` ile silin.

## 2. Geri alma (rollback)

**Önce bakın: deploy bir migration çalıştırdı mı?**

```bash
git diff --stat $PREV $NEW -- backend/alembic/versions
```

**Migration yoksa:**

```bash
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$PREV/" .env
git checkout $PREV
dc up -d
```

**Migration varsa:** eski imajın `migrate` adımı veritabanındaki yeni revizyonu tanımaz ve backend'i başlatmaz. Önce şemayı **yeni** imajla geri indirin, sonra etiketi değiştirin:

```bash
OLD_HEAD=$(docker run --rm agentic-cfo-backend:$PREV alembic heads | awk '{print $1}')
dc run --rm migrate alembic downgrade $OLD_HEAD      # IMAGE_TAG hâlâ $NEW
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$PREV/" .env && git checkout $PREV
dc up -d
```

Downgrade bir sütun/tabloyu düşürüyorsa o sütundaki veri gider (CLAUDE.md DISPATCH: sahibe sorun). Downgrade başarısızsa: deploy öncesi yedekten geri yükleyin (§5).

## 3. Yedek

- Her gece 02:15'te `scripts/backup.sh` (cron, [staging.md §4.10](staging.md)). Log: `/var/log/aicfo-backup.log`.
- İçerik: `pg_dump -Fc` + `uploads/` + `MANIFEST` (sha256'lar, alembic revizyonu, tablo başına satır sayısı, dosya sayısı) → tek tar → `age` ile şifreli → `BACKUP_RCLONE_REMOTE`'a.
- Saklama: uzakta 14 gün (`BACKUP_RETENTION_DAYS`), sunucuda son 2 arşiv.
- Şifre çözme anahtarı **sunucuda yoktur**; sahibin parola yöneticisindedir.
- Başarı işareti: `/var/backups/aicfo/last-success` (uzak kopya doğrulanınca yazılır, [staging.md §9](staging.md#9-yedek-başarısını-izlemek)).
- Kontrol: `rclone lsl $BACKUP_RCLONE_REMOTE | tail` — en yeni dosya 24 saatten eski olmamalı. Eskiyse logda `backup:` satırlarına bakın; betik herhangi bir hatada sıfırdan farklı çıkar.

## 4. Geri yükleme tatbikatı

Ayda bir, ve her yedek değişikliğinden sonra. Canlı sistemi etkilemez: kendi geçici ağında, port yayınlamayan boş bir Postgres açar ve sonunda siler.

```bash
install -m 600 /dev/stdin /tmp/aicfo-backup.key     # parola yöneticisinden yapıştırın, Ctrl-D
AGE_IDENTITY_FILE=/tmp/aicfo-backup.key ./scripts/restore-drill.sh     # uzaktaki en yeni arşiv
shred -u /tmp/aicfo-backup.key
```

Kontroller: arşiv sha256 → şifre çözme → MANIFEST sha256'ları → boş Postgres'e `pg_restore --exit-on-error` → `alembic current` = yedekteki revizyon → tablo başına satır sayısı (veri olan bir tablo boş ya da eksik gelirse HATA; birkaç satırlık fark, dump ile sayım arasındaki yazmalardır ve UYARI) → uploads dosya sayısı → `scripts/golden_path_check.py` (kodun yapısal kontrolü; veriyi değil, verinin çalışacağı kodu doğrular).

`RESULT: OK` görmeden tatbikat geçmiş sayılmaz. Sonucu ve tarihi bir yere yazın.

## 5. Gerçek geri yükleme (canlıya)

Veri bozulması ya da kaybında. **Önce o anki durumu da yedekleyin** (`./scripts/backup.sh`), sonra:

```bash
dc stop caddy frontend backend worker worker-maintenance       # yazmayı durdur
install -m 600 /dev/stdin /tmp/k && age -d -i /tmp/k <arşiv>.tar.age | tar -C /tmp -xf - && shred -u /tmp/k
B=/tmp/aicfo-<tarih>
dc exec -T postgres dropdb -U aicfo aicfo
dc exec -T postgres createdb -U aicfo aicfo
dc exec -T postgres pg_restore -U aicfo -d aicfo --no-owner --exit-on-error < $B/db.dump
dc run --rm --no-deps -T --entrypoint sh backend -c 'rm -rf /app/uploads/* && tar -C /app -xzf -' < $B/uploads.tar.gz
rm -rf $B
dc up -d
```

Arşivin alembic revizyonu çalışan imajdan eskiyse `migrate` onu ileri taşır; yeniyse o revizyonun imajına geçin (§2).

## 6. Olay adımları

İlk 10 dakika: **ne bozuk, ne zamandan beri, kim etkileniyor** — bir yere yazın, sonra:

| Belirti | Bakılacak | Olası çözüm |
|---|---|---|
| Site hiç açılmıyor / TLS hatası | `dc ps`, `dc logs caddy` | DNS IP'yi gösteriyor mu; 80/443 açık mı; `caddy_data` volume'u silinmediyse sertifika oradadır. |
| 502 | `dc ps backend frontend`, `dc logs --tail=200 backend` | `migrate` başarısız mı (§1); Postgres/Redis healthy mi. |
| Analizler "analyzing"de kalıyor | `dc logs worker`, `dc exec redis redis-cli ZCARD arq:queue:analysis` | Worker çalışıyor mu; reaper 10 dakikada bir süresi geçmiş işleri kapatır. `dc restart worker`. |
| Zamanlanmış işler çalışmıyor | `dc logs worker \| grep -i scheduler` | `CFO Scheduler started` yoksa `SCHEDULER_PROCESS`/`SCHEDULER_ENABLED`'a bakın. API'de "not started … owned by worker" satırı beklenen durumdur. |
| Disk doluyor | `df -h`, `docker system df` | Eski imajlar (§1), `/var/backups/aicfo`. Loglar konteyner başına 5×20 MB ile sınırlı. |
| Postgres "too many connections" | `dc exec postgres psql -U aicfo -c 'select count(*) from pg_stat_activity'` | Süreç sayısı artırıldıysa `DB_POOL_SIZE`'ı düşürün (`backend/app/config.py` hesabı). |
| **Veri sızıntısı şüphesi** | Erişim logları (`dc logs caddy`), `JobLog`/audit tabloları | Sahibi hemen arayın. KVKK: ihlal Kurul'a ve ilgili kişilere bildirilir — süre ve içerik için hukukçuya danışın; kanıtı silmeyin, konteynerleri yeniden oluşturmadan önce logları kopyalayın. |

Olay kapandıktan sonra: ne oldu, neden, neyi değiştirdik — kısa bir not ve gerekiyorsa bu runbook'a bir satır.
