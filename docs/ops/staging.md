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
| Boyut | **4 vCPU / 8 GB RAM / 160 GB SSD** |
| İşletim sistemi | Ubuntu 24.04 LTS |
| Konum | Türkiye'deki bir veri merkezi — sözleşmede yazılı olsun (KVKK) |
| Ağ | Sabit IPv4; 22, 80, 443 açık |

Bellek bütçesi henüz ölçülmedi: worker hiç gerçek bir ortamda çalışmadı. İlk hafta `docker stats` ile bakılır, gerekirse servis başına `mem_limit` eklenir. Postgres `max_connections=200` ile başlar: bağlantı havuzu hesabı (2 uvicorn + 2 arq süreci × 30) varsayılan 100'ü aşıyordu.

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
   - `BACKEND_SECRET_KEY`, `NEXTAUTH_SECRET` → `openssl rand -base64 32`
   - `NEXTAUTH_URL=https://<APP_DOMAIN>`, `BRAND_DOMAIN`, `PILOT_*`, `OPENAI_API_KEY`/`LLM_*`, `SMTP_*`
   - `OPEN_BANKING_SANDBOX`, `GIB_SANDBOX`: staging'de `true` kalır.
   - `USE_SQLITE`, `POSTGRES_HOST`, `REDIS_URL`, `SCHEDULER_PROCESS`, `ALLOW_INLINE_JOB_FALLBACK`'i compose dosyası kendisi koyar; `.env`'deki değerleri geçersizdir.
6. **Yedek anahtarı — sahibin dizüstünde**
   ```bash
   age-keygen -o aicfo-backup.key      # özel anahtar: parola yöneticisine, sunucuya DEĞİL
   ```
   Çıktıdaki `age1…` genel anahtarı sunucudaki `.env`'e `AGE_RECIPIENT=` olarak yazılır.
7. **Yedek hedefi**: `rclone config` ile 3. bölümdeki depolamaya bir remote tanımlayın; `.env`'e `BACKUP_RCLONE_REMOTE=<remote>:<klasör>`. Deneme: `rclone lsd <remote>:`.
8. **DNS**: `app.` ve `api.` için VPS IP'sine A kaydı (IPv6 varsa AAAA). İlk `up`'tan **önce** çözülüyor olmalı (`dig +short api.<alan>`); yoksa Let's Encrypt denemeleri hız sınırına takılır.
9. **İlk açılış**
   ```bash
   sed -i "s/^#\? *IMAGE_TAG=.*/IMAGE_TAG=$(git rev-parse --short HEAD)/" .env
   docker compose -f docker-compose.prod.yml up -d --build
   docker compose -f docker-compose.prod.yml ps        # hepsi healthy / migrate exited (0)
   curl -fsS https://<API_DOMAIN>/health               # {"status":"ok"}
   docker compose -f docker-compose.prod.yml logs worker | grep -i scheduler   # "CFO Scheduler started"
   ```
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
