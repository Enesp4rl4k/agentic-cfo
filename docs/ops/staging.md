# Staging: tek bir Türkiye VPS'i üzerinde docker-compose

*Altı haftalık plan (2026-11-20), 2. hafta. Sahibin kararı: staging Türkiye'de bir VPS'te, docker-compose ile çalışır — KVKK gereği veri Türkiye'de kalır. Bu belge kurulumu; günlük işler (deploy, geri alma, yedek, geri yükleme, olay) [runbook.md](runbook.md)'dedir.*

## 1. Ne çalışıyor

```
internet ──80/443──▶ caddy ──▶ frontend:3000     (APP_DOMAIN)
                           └─▶ backend:8000      (API_DOMAIN)
                                  │
            ┌─────────────────────┼────────────── internal ağ (internal: true, dışarı yolu yok)
            ▼                     ▼
        postgres (pgvector)     redis ◀── worker (arq + APScheduler)
                                      ◀── worker-maintenance (arq)
migrate: her deploy'da bir kez `alembic upgrade head`; backend ancak o 0 ile çıkınca başlar.
```

- Dışarıya yalnız Caddy açılır (80, 443, 443/udp). Postgres ve Redis'in yayınlanmış portu yoktur; `internal` ağın internete çıkışı yoktur. `tests/test_scheduler_process.py` bunu dosya üzerinden kontrol eder.
- İki alan adı: `app.` frontend'e, `api.` backend'e gider. Tek alan adıyla `/api → backend` yönlendirmesi NextAuth'un `/api/auth` yolunu kırar.
- Zamanlanmış işler (APScheduler) yalnız `worker` konteynerinde çalışır: `SCHEDULER_PROCESS=worker`. API süreçleri başlatmaz (önceden her uvicorn süreci başlatıyordu). Her iş ayrıca Redis kilidiyle sarılı; `worker` çoğaltılırsa bir tik yine bir kez çalışır.
- TLS sertifikalarını Caddy Let's Encrypt'ten kendisi alır ve yeniler.

## 2. Sunucu

| | |
|---|---|
| Boyut | **4 vCPU / 12 GB RAM / 160 GB SSD** (bellek alt sınırı için aşağıya bakın) |
| İşletim sistemi | Ubuntu 24.04 LTS |
| Konum | Türkiye'deki bir veri merkezi — sözleşmede yazılı olsun (KVKK) |
| Ağ | Sabit IPv4; 22, 80, 443 açık |

Her servisin bellek/CPU sınırı `docker-compose.prod.yml`'de vardır (üst sınırdır, rezervasyon değil). Bu boyuttaki bir VPS için başlangıç değerleri:

| Servis | `mem_limit` | `cpus` | Not |
|---|---|---|---|
| postgres | 2g | 2 | `shared_buffers=1GB`, `max_connections=200` |
| redis | 640m | 0.5 | `maxmemory 512mb` + AOF yeniden yazma payı |
| backend | **2560m (en az)** | 2 | 2 uvicorn süreci (her biri ~350 MB) + süreç başına bir ayrıştırıcı çocuk (en çok `PARSE_CHILD_RSS_MB` = 800 MB) |
| worker | **2g (en az)** | 2 | analizler + zamanlanmış işler + bir ayrıştırıcı çocuk (800 MB) |
| worker-maintenance | 768m | 1 | |
| frontend | 512m | 1 | |
| caddy | 256m | 0.5 | |
| migrate | 512m | 1 | tek seferlik |

**Bellek alt sınırı:** API konteyneri en az **2,5 GB**, worker en az **2 GB**, bunlara Postgres (2 GB) ve Redis (640 MB) eklenir; yukarıdaki sınırların toplamı yaklaşık 8,8 GB'dır (`migrate` tek seferlik, hesaba girmez), bu yüzden makine **12 GB** olmalıdır. 8 GB'lık makinede bütün sınırlar aynı anda dolmaz ama bunun garantisi yoktur; dolarsa çekirdeğin OOM killer'ı bir süreci öldürür. Ayrıştırıcı çocuk ise `PARSE_CHILD_RSS_MB` (800 MB) aşılınca kendiliğinden durdurulur ve kullanıcı "dosya bellek sınırını aştı" iletisini görür. Neden: [parser-sizing.md](parser-sizing.md). `backend` ve `worker` sınırlarını bunların altına indirmeyin: açılışta `parser_memory_exceeds_container` uyarısı görürsünüz. Bu değerler **ölçülmedi**: ilk hafta `docker stats` ile bakın; bir servis sınırında `OOMKilled` oluyorsa (`docker inspect -f '{{.State.OOMKilled}}' <konteyner>`) o servisin `mem_limit`'ini artırın, makineyi büyütmeden önce. Daha küçük bir VPS için önce Postgres'in `shared_buffers`'ını ve `mem_limit`'ini birlikte düşürün.

Loglar her konteynerde `json-file`, **5 dosya × 20 MB** ile döner (konteyner başına en çok 100 MB). Caddy erişim logu da aynı sınırdadır.

Postgres `max_connections=200` ile başlar: bağlantı havuzu hesabı (2 uvicorn + 2 arq süreci × 30) varsayılan 100'ü aşıyordu.

## 3. Sahibin açması gereken hesaplar

| Hesap | Ne için | Not |
|---|---|---|
| **VPS sağlayıcısı** (Türkiye) | Uygulamanın kendisi | Yukarıdaki boyut. |
| **Yedek depolama** (Türkiye, VPS'ten ayrı) | Gece yedeklerinin sunucu dışı kopyası | rclone'un konuşabildiği bir şey: S3 uyumlu nesne deposu, SFTP'li ikinci bir sunucu vb. Aynı sağlayıcının aynı veri merkezi "sunucu dışı" sayılmaz. |
| **Alan adı** | `app.` ve `api.` alt alan adları | DNS'i yönetebileceğiniz bir kayıt firması. |
| **İşlem e-postası sağlayıcısı** (SMTP) | Uyarılar, davetler, özetler | `SMTP_HOST/PORT/USER/PASSWORD`, `NOTIFICATION_FROM`. Sağlayıcı yurt dışındaysa bu bir yurt dışı aktarımdır — KVKK değerlendirmesi gerekir. Alan adınızda SPF/DKIM kayıtlarını sağlayıcı verir. |
| **Sentry** | Hata takibi | **Henüz bağlı değil:** `init_sentry` `settings.sentry_dsn` okur ama `Settings`'te bu alan yok, yani `SENTRY_DSN` şu an yok sayılır. Bağlanması ayrı bir iş; Sentry de yurt dışı aktarımdır. |

## 4. Kurulum (bir kez)

Komutlar sunucuda, `deploy` kullanıcısıyla. Sahibin dizüstünde yapılacaklar ayrıca belirtildi.

1. **Kullanıcı ve güvenlik duvarı**
   ```bash
   adduser --disabled-password deploy && usermod -aG sudo,docker deploy   # docker grubu 3. adımdan sonra var
   ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp && ufw enable
   ```
   SSH yalnız anahtarla (`PasswordAuthentication no`). Docker yayınlanan portlarda ufw'yu atlar; burada yalnız Caddy port yayınladığı için sonuç aynıdır.
2. **Docker Engine + compose eklentisi**: docs.docker.com/engine/install/ubuntu adımlarıyla.
3. **Araçlar**: `sudo apt install -y git age rclone python3`
4. **Kod**
   ```bash
   sudo mkdir -p /opt/agentic-cfo && sudo chown deploy: /opt/agentic-cfo
   git clone <repo> /opt/agentic-cfo && cd /opt/agentic-cfo
   cp .env.example .env && chmod 600 .env
   ```
5. **`.env`'i doldurun** (dosyanın sonundaki "Staging" bölümü + mevcut anahtarlar):
   - `APP_DOMAIN`, `API_DOMAIN`, `ACME_EMAIL`
   - `POSTGRES_PASSWORD` → `openssl rand -hex 24` (Redis'in parolası yok: yalnız backend konteynerlerinin girebildiği `internal` ağda)
   - `BACKEND_SECRET_KEY` (en az 32 karakter) ve `NEXTAUTH_SECRET` → `openssl rand -base64 32`. İkisi de şablon değerde kalırsa ön kontrol (preflight) konteyneri **başlatmaz**.
   - `BRAND_DOMAIN`, `SUPPORT_CONTACT`, `PLATFORM_OPERATOR_EMAILS`, `OPENAI_API_KEY`/`LLM_*`, `SMTP_*`, `NOTIFICATION_FROM` ([§8](#8-sahibin-açık-kararları) hangi karar için hangi değişken olduğunu söyler).
   - `APP_ENV`: boş bırakın (= `production`); bu kutu staging ise `APP_ENV=staging`.
   - `OPEN_BANKING_SANDBOX`, `GIB_SANDBOX`: staging'de `true` kalır.
   - Compose dosyası kendisi koyar, `.env`'deki değerleri geçersizdir: `APP_ENV`, `USE_SQLITE`, `POSTGRES_HOST/PORT`, `REDIS_URL`, `SCHEDULER_PROCESS=worker`, `TRUSTED_PROXY_COUNT=1`, `ALLOW_INLINE_JOB_FALLBACK=false`, `GIT_SHA`, `BACKEND_CORS_ORIGINS`, `FRONTEND_URL`, `BRAND_APP_URL`, `BACKEND_URL`, frontend'in `NEXTAUTH_URL`/`NEXT_PUBLIC_API_URL`'i (hepsi `APP_DOMAIN`/`API_DOMAIN`'den).
   - Kayıt (kimler hesap açabilir) için `.env`'de bugün bir değişken **yoktur**: kayıt açıktır ([§8](#8-sahibin-açık-kararları), karar D1). Eski `PILOT_*` değişkenlerini hiçbir kod okumaz; yazmayın.
   - Tam liste: [configuration.md](configuration.md). Hangi servis `.env`'in neresini görür: aynı dosyanın §3'ü. Frontend `.env`'i **hiç görmez**; yalnız `NEXT_PUBLIC_API_URL`, `NEXTAUTH_URL`, `NEXTAUTH_SECRET` alır.
6. **Yedek anahtarı — sahibin dizüstünde**
   ```bash
   age-keygen -o aicfo-backup.key      # özel anahtar: parola yöneticisine, sunucuya DEĞİL
   ```
   Çıktıdaki `age1…` genel anahtarı sunucudaki `.env`'e `AGE_RECIPIENT=` olarak yazılır.
7. **Yedek hedefi**: `rclone config` ile 3. bölümdeki depolamaya bir remote tanımlayın; `.env`'e `BACKUP_RCLONE_REMOTE=<remote>:<klasör>`. Deneme: `rclone lsd <remote>:`.
8. **DNS**: `app.` ve `api.` için VPS IP'sine A kaydı (IPv6 varsa AAAA). İlk `up`'tan **önce** çözülüyor olmalı (`dig +short api.<alan>`); yoksa Let's Encrypt denemeleri hız sınırına takılır.
9. **İlk açılış**: [§6.1](#61-birinci-deploy-ilk-kurulum) sırasını izleyin (ön kontrol, smoke test ve `ready` dahil).
10. **Gece yedeği** (`crontab -e`, deploy kullanıcısı):
    ```
    15 2 * * * cd /opt/agentic-cfo && ./scripts/backup.sh >> /var/log/aicfo-backup.log 2>&1
    ```
    Bir kez elle çalıştırın ve uzakta dosyayı görün.
11. **İlk geri yükleme tatbikatı — gerçek veri girmeden önce.** [runbook.md §4](runbook.md#4-geri-yükleme-tatbikatı). Tatbikatı geçmemiş bir yedek, yedek sayılmaz.

## 5. Bilinen açıklar (bu PR kapatmıyor)

- **Worker hiç gerçek ortamda çalışmadı.** Bu makinede Docker daemon, Postgres ve Redis yok; compose dosyası yalnız `docker compose config` ile doğrulandı. İlk açılış, worker'ın ilk gerçek çalışmasıdır — logları izleyin.
- **LangGraph checkpoint'i Postgres'te değil.** `langgraph-checkpoint-postgres` paketi kurulu değil; uygulama bunu yüksek sesle söyleyip belleğe düşer (yarım kalan bir analiz yeniden hesaplanır, veri kaybı yok).
- **Marka değişkenleri tarayıcı paketine girmiyor.** `frontend/src/lib/branding.ts` `NEXT_PUBLIC_BRAND_*`'ı dinamik okur; Next.js yalnız harfiyen yazılan `process.env.NEXT_PUBLIC_X`'i derlemeye gömer. `NEXT_PUBLIC_API_URL` için Dockerfile'a build argümanı eklendi (önceden paket `http://localhost:8000`'e gidiyordu); marka için ayrı iş.
- **Sentry bağlı değil** (3. bölüm).
- **Outbox e-posta göndericisi** PR #56 ile geliyor; bu kurulum ona bağlı değil.
- **Konteyner başlatma sarmalayıcısı, `arq --check` sağlık kontrolü ve Caddyfile'ın yeni yönergeleri** (`timeouts`, `?Header`, `header_up`, `transport`) yalnız statik doğrulandı (`scripts/check-prod-compose.sh`: `docker compose config` + yapısal kurallar). Hiçbiri bir konteynerde çalıştırılmadı; ilk açılışta `docker compose ps` (worker'lar `healthy` olmalı) ve `docker compose logs caddy` ile doğrulayın.
- **Worker ve zamanlayıcı tek konteyner.** Ayrı bir `scheduler` servisi yoktur: APScheduler `worker` içinde (`SCHEDULER_PROCESS=worker`) çalışır, o konteynerin sağlık kontrolü ve `stop_grace_period`'u zamanlayıcıyı da kapsar. Uygulamanın sağlık kontrolü, arq'nin Redis'teki sağlık anahtarıdır (30 sn'de bir yenilenir): bir cron'un takılıp worker'ın yaşaması bu kontrolle yakalanmaz; onu `/api/v1/ready`'nin `scheduler` kontrolü (son outbox geçişinin yaşı) gösterir.
- **Konteyner başına gizli bilgi kapsamı kısmi.** Frontend `.env`'i görmez, ama dört backend konteyneri `.env`'in tamamını okur (ayarların çoğuna ihtiyaçları var); `NEXTAUTH_SECRET` da onlara girer (ön kontrol şablon değeri yakalasın diye).

## 6. Deploy kontrol listesi

Tek sıra, her adım bir öncekinden sonra. `dc` = `docker compose -f docker-compose.prod.yml` (runbook'taki `alias dc=...`). Sunucuda, `/opt/agentic-cfo` içinde, `deploy` kullanıcısıyla. Ayrıntı ve olay durumları: [runbook.md](runbook.md); sürüm sonrası kontroller ve geri alma sayfası: [runbooks/deploy-and-rollback.md](runbooks/deploy-and-rollback.md).

### 6.1 Birinci deploy (ilk kurulum)

1. [§8](#8-sahibin-açık-kararları)'deki kararlar verildi ve değişkenleri `.env`'e yazıldı; [§4](#4-kurulum-bir-kez) adım 1-8 tamam (sunucu, Docker, `.env`, yedek anahtarı, rclone, DNS çözülüyor).
2. `sed -i "s/^#\? *IMAGE_TAG=.*/IMAGE_TAG=$(git rev-parse --short HEAD)/" .env` (yoksa satırı ekleyin).
3. `dc build`
4. **Migrate**: `dc run --rm migrate alembic upgrade head`: boş veritabanını head'e getirir.
5. **Ön kontrol**: `dc run --rm migrate python -m app.core.preflight --db`: çıktı `PREFLIGHT ok (production)` olmalı. `FATAL` satırı varsa düzeltin (konteynerler zaten başlamaz). `WARN` satırlarını (posta göndericisi yok, hata takibi yok...) okuyun; her biri bir sahip kararına karşılık gelir ([§8](#8-sahibin-açık-kararları)).
6. **Başlat**: `dc up -d`; `dc ps`: `migrate` exited (0), diğerleri `healthy` (worker'lar ilk 90 sn `starting` kalabilir).
7. **Smoke test**: `./scripts/smoke-test.sh --api https://<API_DOMAIN> --app https://<APP_DOMAIN> --expect-commit "$(git rev-parse --short HEAD)"`: hiç `FAIL` olmamalı.
8. **Hazırlık**: `curl -fsS https://<API_DOMAIN>/api/v1/ready`: `"status": "ready"`. İlk beş dakika `degraded` olabilir (zamanlayıcının ilk outbox geçişi); beş dakika sonra `smoke-test.sh ... --strict` ile yeniden çalıştırın.
9. Zamanlayıcı: `dc logs worker | grep -i scheduler` → `CFO Scheduler started`.
10. Gece yedeği cron'u ([§4](#4-kurulum-bir-kez) adım 10), bir elle çalıştırma ve ilk geri yükleme tatbikatı (adım 11) **gerçek veri girmeden önce**.

### 6.2 Yükseltme (her deploy)

1. **Yedek**: `./scripts/backup.sh`. Hata verirse deploy etmeyin. `cat /var/backups/aicfo/last-success` bugünün saatini göstermeli.
2. **Çek**: `PREV=$(grep '^IMAGE_TAG=' .env | cut -d= -f2)`; `git fetch origin && git checkout <sha>`; `NEW=$(git rev-parse --short HEAD)`. Migration listesine bakın: `git diff --stat $PREV $NEW -- backend/alembic/versions`. Sütun/tablo düşüren bir migration varsa önce sahibe sorun.
3. `sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$NEW/" .env && dc build` (eski konteynerler hâlâ çalışıyor).
4. **Migrate**: `dc run --rm migrate alembic upgrade head`. Hata verirse eski konteynerler çalışmaya devam eder; geri alma için §7.
5. **Ön kontrol**: `dc run --rm migrate python -m app.core.preflight --db` → `PREFLIGHT ok (production)`.
6. **Başlat**: `dc up -d`; `dc ps` hepsi `healthy`. (Kısa kesinti olur: konteynerler yeniden oluşur; mesai dışında yapın.)
7. **Smoke test**: adım 6.1/7'deki komut, `--expect-commit $NEW`.
8. **Hazırlık**: `curl -fsS https://<API_DOMAIN>/api/v1/ready` → `ready` (ilk beş dakika `degraded` olabilir).
9. `PREV`, `NEW` ve saati bir yere not edin.

Adım 4-5 `dc up -d` içinde de çalışır (`migrate` servisi ve her servisin başlangıç ön kontrolü); onları elle önce çalıştırmak, bir hatanın eski konteynerler değiştirilmeden görünmesi içindir.

## 7. Geri alma

Adım adım komutlar: [runbook.md §2](runbook.md#2-geri-alma-rollback); sonrasında yapılacak kontroller: [runbooks/deploy-and-rollback.md](runbooks/deploy-and-rollback.md). Özet:

1. **Migration yoksa**: `IMAGE_TAG`'i `$PREV` yapın, `git checkout $PREV`, `dc up -d`.
2. **Geri alınabilir migration varsa**: yeni imajla `alembic downgrade <eski head>`, sonra etiketi `$PREV` yapın ve `dc up -d`. Düşüren bir downgrade o sütunun verisini siler.
3. **Geri alınamayan migration** (`downgrade()` yok ya da hata veriyor, veri değişmiş, ya da veri kaybı kabul edilemez): **adım 6.2/1'de aldığınız deploy öncesi yedekten geri yükleyin** ([runbook.md §5](runbook.md#5-gerçek-geri-yükleme-canlıya), [runbooks/db-restore.md](runbooks/db-restore.md)): önce o anki durumu da yedekleyin, servisleri durdurun, `db.dump` ve `uploads`'ı yükleyin, `IMAGE_TAG`'i `$PREV` yapıp `git checkout $PREV`, `dc up -d`. **Yedekten sonra girilen veri kaybolur**: sahibe söyleyin.
4. Her durumda: smoke test (`--expect-commit $PREV`) ve `python -m app.core.preflight --db`.

## 8. Sahibin açık kararları

Karar numaraları [operational-readiness-2026-11.md](operational-readiness-2026-11.md)'dendir. Hiçbiri verilmeden gerçek şirket verisi girilmez.

| Karar | Ne seçilecek | Ayarlanacak değişken (`.env`'de, sunucuda) | Not |
|---|---|---|---|
| D8 Barındırma sağlayıcısı | Türkiye'de VPS ([§2](#2-sunucu)'deki boyut) | yok; sunucunun IP'si DNS'e girer | Diğer kararları açar. |
| D8 Alan adları | iki alt alan adı | `APP_DOMAIN`, `API_DOMAIN`, `ACME_EMAIL` | `app.` ve `api.` için A kaydı; compose bunlardan CORS, `FRONTEND_URL`, `BACKEND_URL` türetir. |
| D2 Posta sağlayıcısı | Türkiye/AB bölgeli işlem e-postası | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFICATION_FROM` | Alan adında SPF/DKIM: [mail.md](mail.md). Ayarsızsa her e-posta başarısız outbox satırı olur ve ön kontrol uyarır. |
| D3 Yedek hedefi | VPS'ten ayrı, Türkiye'de nesne deposu | `AGE_RECIPIENT` (`age1...` genel anahtar), `BACKUP_RCLONE_REMOTE` (`remote:klasör`), `BACKUP_RETENTION_DAYS` (14) | Özel anahtar parola yöneticisinde; sunucuda `rclone config` ile remote tanımlı olmalı. |
| D4 Uyarı kanalı | `https://<API_DOMAIN>/api/v1/ready` için bir uptime izleyici + yedek kalp atışı | uygulamada değişken yok; izleyicinin adresi sahipte | [§9](#9-yedek-başarısını-izlemek). |
| D5 Hata takibi | Sentry (AB bölgesi) ancak KVKK kontrolünden sonra | `SENTRY_DSN`, `SENTRY_ENVIRONMENT` | Boş bırakmak geçerli: hatalar konteyner logunda. [§3](#3-sahibin-açması-gereken-hesaplar)'e bakın. |
| D6 LLM sağlayıcısı | hukukçuyla; rakamlar LLM'siz çalışır | `OPENAI_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | |
| D1 Kim kayıt olabilir | kapalı kayıt | **bugün yok**: kayıt açık, `PILOT_*` değişkenlerini kod okumaz | Ayrı bir PR gerçek ayarı getirecek; getirdiğinde bu satır ve [configuration.md](configuration.md) güncellenir. Şimdilik `users` tablosunu izleyin. |
| D7 Silme politikası | yalnız anonimleştirme | `ORG_ERASURE_HARD_DELETE_ENABLED=false` | |

Sabit gizliler (karar değil, kurulum): `POSTGRES_PASSWORD`, `BACKEND_SECRET_KEY`, `NEXTAUTH_SECRET` (rastgele, üretim komutları [§4](#4-kurulum-bir-kez) adım 5'te).

## 9. Yedek başarısını izlemek

- `scripts/backup.sh` her başarılı çalışmanın sonunda (uzak kopya doğrulandıktan sonra) `/var/backups/aicfo/last-success` dosyasına UTC saati ve arşiv adını yazar. Dosya 26 saatten eskiyse yedek çalışmamıştır: `find /var/backups/aicfo -maxdepth 1 -name last-success -mmin +1560` çıktı veriyorsa uyarın.
- Başarısızlık sıfırdan farklı çıkış kodu ve `/var/log/aicfo-backup.log`'da `backup:` satırlarıdır; cron çıktısı kimseye gitmez, bu yüzden uyarı kanalı (D4) bu dosyaya ya da uzaktaki en yeni arşivin yaşına (`rclone lsl`) bakmalıdır.
- **Uygulamaya bildirme (henüz yok):** `fix/pilot-blockers` PR'ı uygulamaya bir yedek-başarısı bildirme uç noktası eklerse (ve `/api/v1/ready` bunu gösterirse), `backup.sh`'in sonuna o uç noktaya bir çağrı eklenir ve bu bölüm güncellenir. Bu PR onu uygulamaz.
