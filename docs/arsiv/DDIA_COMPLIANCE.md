# DDIA Uyumluluk Raporu — *Designing Data-Intensive Applications* Prenipleri

> Denetim tarihi: 2026-09-23 · Kapsam: `backend/app` + deployment tanımları
> Bu belge her satırda **kanıt** (dosya + test) ve **kalan boşluğu** birlikte
> verir. "Uyumludur" iddiası kanıtsız yazılmamıştır; test adı vermeyen satır
> henüz kapatılmamıştır.

Doğrulama komutları (hepsi bu denetimde yeşil):

```bash
python -m pytest tests -q          # tüm suite (aşağıda güncel sayı)
ruff check app                     # All checks passed
mypy --config-file mypy_strict.ini # 155 dosya, 0 hata (CI gate)
```

---

## Ch.1 — Güvenilirlik / Ölçeklenebilirlik / Sürdürülebilirlik

| Prensip | Kanıt (kod) | Kanıt (test) | Durum |
|---|---|---|---|
| Tek noktada LLM denetimi (maliyet + kalite chokepoint) | `platform/model_gateway.py` | `tests/test_llm_router*.py` | ✅ |
| Önbellek I/O'su tek havuzdan: op başına TCP handshake yok (eski: her get/set'te `from_url` + `aclose`) | `services/cache_service._get_redis` → `core/redis_client` | `test_redis_fallbacks.py::test_cache_ops_never_close_the_shared_client` | ✅ |
| Broker `volatile-lru` eviction'i önbelleğin hafızasını silmez (ikinci katman kurtarır) | `CacheService.get` miss → `_get_memory` | `test_broker_eviction_rescues_from_the_memory_tier` | ✅ |
| Ölçülebilir güvenilirlik (retry bütçesi, idempotent iş) | `worker.py` (`max_tries`, transient sınıflandırma) | `test_agents/test_maintenance_worker.py` | ✅ |
| Tekrar çalıştırılabilirlik = yeniden hesaplama | `services/job_state.purge_job_outputs` + worker sırası | `test_job_state.py::TestPurge` | ✅ |
| Ağ/LLM çağrısı açık write transaction içinde **olmaz** | worker: pipeline öncesi `db.rollback()`, RAG ayrı session, `rag_service` embed'i delete'ten önce | `test_job_state.py`, worker akış testleri | ✅ |

## Ch.2 — Veri modeli ve sorgular

| Prensip | Kanıt | Durum |
|---|---|---|
| İlişkisel çekirdek + şema, JSON yalnızca geçerli değişken meta için | `app/models/*` (110+ model), `alembic/versions/` (039 revizyon) | ✅ |
| İndeks = sorgu sözü: rapor filtreleri ve reaper taraması index'li | migration `038`, `039` (`ix_analysis_jobs_status_lease`, `ix_canonical_transactions_org_date`) | ✅ |
| `mypy`/`ruff` kalite ratchet'i | `mypy_strict.ini` (155 dosya gate) | ✅ |

## Ch.3 — Encoding: JSON, XML, binary

| Prensip | Kanıt | Durum |
|---|---|---|
| Ham byte üretici→tüketicide bozulmadan iletilir (kuruş tam sayı) | `Transaction.amount_kurus: int`, TR dikey testleri | ✅ |
| Büyük veri akışında bellek sabit kalır | `upload_service.stream_to_disk` 64KB chunk + `.part`→`os.replace` | ✅ |
| Yük denetimi (XML entity expansion) | `validate_xml_payload` upload'ta parse öncesi | ✅ |
| Sıra-korunan, backpressure'li olay akışı | `streaming/sse.py` (drop-oldest ring, `maxsize=100`) | ✅ `test_sse_bus.py` |
| *(bilinçli kabul)* ARQ job argümanları pickle'lanır — broker güvenilir ağda olmalı | `worker.py` (ARQ varsayılanı) | ⚠️ dokümante |

## Ch.4 — Encoding evrimi (backward/forward compatibility)

| Prensip | Kanıt | Durum |
|---|---|---|
| Eski istemci yeni alanlara takılmaz (ekleme-uyumlu enum + `get(..., default)`) | connector `TR`, API `data/error` sarmalayıcı | ✅ `test_route_sweep` |
| Migration zinciri downgrade destekler | her `alembic/versions/*.py` + 039 downgrade test edildi (stamp→up→down→up) | ✅ |

## Ch.5 — Replikasyon

| Prensip | Durum |
|---|---|
| Tek writer'lı Postgres (tek doğruluk kaynağı) | ✅ `database.py` |
| Disk write'ları all-or-nothing: crash asla yarım dosya yayımlayamaz | ✅ `core/atomic_io.py` → 9 çağrı yeri; `test_atomic_io.py` |
| Küçük ölçek için replikasyon/yedeklilik **kasten yok** | ⚠️ boşluk: prod'da `pg_dump`/PITR kurulumu operasyon sorumluluğu |

## Ch.6 — Bölütleme (partitioning)

| Prensip | Kanıt | Durum |
|---|---|---|
| Anahtar-ileri dağıtım: iş kuyruğu job_id'ye göre bölünür | ARQ `job_timeout`, bakım/ayrıntı kuyrukları | ✅ |
| Artan anahtar üzerinde keyset büyümesi denetimi | ⚠️ `OFFSET` pagination duruyor (`api/analysis.py` listeler) | 🔶 kısmi |
| Redis bellek politikası TTL'siz anahtarları **asla** eviction'e kurban etmez | `volatile-lru` (compose/k8s/helm) | ✅ bu denetimde düzeltildi |
| Kapasite aritmetiği görünür: süreç × havuz ≤ max_connections | `config.db_pool_size/db_max_overflow` + yorum | ✅ |
| Ayrıştırma anahtarında sıcaklık dengesi (tek org'a segment yok) | `job_id` + `org_id` çift indeksli | ✅ |

## Ch.7 — Transaction'lar ve concurrency (⭐ bu denetimin çekirdeği)

| Prensip | Kanıt (kod) | Kanıt (test) | Durum |
|---|---|---|---|
| **Check-then-act yok**: claim tek atomik `UPDATE ... WHERE status IN(...)`; rowcount = karar | `services/job_state.claim_for_analysis` | `test_job_state.py::TestClaim` (ikinci claim `None`) | ✅ |
| Çıktılar + terminal durum **tek transaction**; `finish_job` commit etmez, sahibi commit eder | `worker.run_cfo_analysis` finish→commit sırası | `test_finish_does_not_commit_behind_the_callers_back` | ✅ |
| Geç terminal durum **asla** geç yazılamaz (reaper'ın kararı son sözdür) | finish/fail `WHERE status IN ('ingesting','analyzing')` | `test_a_job_the_reaper_took_is_not_overwritten` | ✅ |
| Hata yolunda **önce rollback**: kısmi veri FAILED satırının altına sızmaz | `worker.py` except bloğu | `test_job_state.py` + worker testleri | ✅ |
| Çift onay yarışı: iki approver'dan biri 409 alır | `api/analysis.approve` atomik `WHERE awaiting_review` | `test_review_approval.py` | ✅ |
| Lease: crashed worker'ın claim'i saati geçince biter | `analysis_jobs.lease_expires_at` + migration 039 | `test_job_reaper.py` | ✅ |
| Yavaş ağ çağrısı write transaction **içinde** durmaz: RAG re-index embed'i delete'ten önce | `rag_service.index_job_text` sırası (embed → delete → insert) | `test_rag_service.py::test_embedding_runs_before_the_transaction_opens` | ✅ |
| Reaper: ölü iş, ele alınmamış kuyruk, yarım ledger hepsi kapanır | `services/job_reaper.reap_stuck_jobs` | `test_job_reaper.py` (3 sınıf) | ✅ |
| `awaiting_review` **reap edilmez** (insan kapısı hata değildir) | reaper `WHERE status IN (ingesting, analyzing)` | `test_awaiting_review_is_a_person_not_a_fault` | ✅ |

## Ch.8 — Dağıtık sistemlerin baş belası

| Prensip | Kanıt | Durum |
|---|---|---|
| Her bekleyişin bir **zaman aşımı** var (ölüm → gözlemlenemezlik) | lease + reaper 10 dk cron (`scheduler.py::stuck_job_reaper`) | ✅ |
| Uçlar arası **tek örnek** koordinasyonu (N uvicorn worker'ı aynı cron'u 1× çalıştırır) | `scheduler._exclusive` Redis NX + TTL-as-release | ✅ (testlerde broker kapalı → yerel davranış) |
| Broker yoksa özellik **sessizce kırılmaz**, yerel fallback'e düşer | `core/redis_client.get_redis() → None` + cooldown | ✅ `test_redis_fallbacks.py` |
| Outage sonrası toparlanma: SSE dinleyicisi backoff ile reconnect | `sse.py::_listener_loop` | ✅ kod (broker'lı test CI'da) |
| Süre/zaman tutarlılığı: rate-limit penceresi tek atomik Lua scripti | `middleware/rate_limit._REDIS_WINDOW_LUA` | ✅ yerel fallback sözleşmesi aynı (`remaining` dahil) |
| ⚠️ Kalan boşluk: saat kayması/sağlık metrikleri (Prometheus) yok | — | 🔶 |

## Ch.9 — Tutarlılık

| Prensip | Kanıt | Durum |
|---|---|---|
| Doğruluk kaynağı = tek veritabanı; süreç-içi bellek yalnızca tampon | claim/finish DB'de; SSE eid dedupe bellekte (kaybetmek = tekrar, kayıp yok) | ✅ |
| Write-after-read yarışları guard'lı (approve, claim, finish) | Ch.7 tablosu | ✅ |
| Publish → durum commit sırası: `done` yalnızca commit'ten sonra gider | `worker.py` | ✅ |
| Multi-process canlı ilerleme artık **gerçekten** çalışıyor (publish ARQ worker'da, subscriber API'de) | `streaming/sse.py` pub/sub köprüsü | ✅ `test_sse_bus.py` (eid, kapasite); broker köprüsü CI redis ile |
| 🔶 Replay/akış günlüğü yok: geç bağlanan istemci adımı SSSE'de (poll replay'i telafi eder) | — | 🔶 bilinçli |

## Ch.10 — Batch processing

| Prensip | Kanıt | Durum |
|---|---|---|
| Yeniden çalıştırma = yeniden hesaplama, birleşim değil | `purge_job_outputs` (Transaction/Report/Anomaly) | ✅ `TestPurge` |
| Deterministik kirli okuma penceresi | worker pipeline öncesi read-txn kapanır | ✅ |
| Batch idempotency: günlük tarama tekrar anomali eklemez | `scheduler._scan_recent_jobs` (`_completed_steps` benzeri job bazlı kontrol) | ✅ mevcut |
| Gece budaması (retention) örnekleri var | `_nightly_usage_prune` | ✅ (audit_log retention **yok** — Ch.12) |

## Ch.11 — Stream processing

| Prensip | Kanıt | Durum |
|---|---|---|
| **Idempotent operation**: duplicate iş teslimi zararsız (claim) | `job_state.claim_for_analysis` | ✅ `test_job_state.py` |
| HTTP kenarında isteğe bağlı `Idempotency-Key` (1 saat NX) | `api/analysis._idempotency_seized` | ✅ `test_redis_fallbacks.py` |
| Kuyruk kaybı değil, yeniden deneme: `max_tries=2` + transient ayrımı + inline fallback | `worker.py` | ✅ `test_maintenance_worker.py` |
| Gözlemleme = dayanıklı defter (`agent_runs`), kapanışı reaper yapar | `run_ledger` + `job_reaper` | ✅ `test_stale_ledger_rows` |
| Event akışında exactly-once **teslimat** per subscriber (eid dedupe, iki yol: lokal + bus) | `sse.py::_deliver_local` | ✅ `test_sse_bus.py::TestDedupe` |

## Ch.12 — Güven ve gizlilik (kalan boşlukların listesi)

| Prensip | Kanıt | Durum |
|---|---|---|
| Köken/provenance (ham metin, confidence, hangi kaynaktan) | `Transaction.raw_text/confidence`, fatura köken alanları | ✅ mevcut suite |
| Ham API key yolu kapatılmalı | `api/auth.py:189` legacy header yolu **duruyor** | 🔶 Faz 0'da kaldı |
| Audit kaydı org'a bölünmeli + retention | `models/audit_log.py` `org_id` **yok** ("never deleted") | 🔶 sahip kararı gerektirir |
| Alan seviyesinde şifreleme varsayılanı | `.env` kullanımı var, **default True değil** | 🔶 sahip kararı gerektirir |
| Secret'lar KV'da, repo'da değil | `.env` gitignore'da ✅ ama deploy default'ları hâlâ insecure (`config._INSECURE_SECRETS` uyarısı ile) | 🔶 deploy sorumluluğu |
| Broker/ckpt paketleri: prod `langgraph-checkpoint-postgres` kurulu değilse checkpoint **sessiz değil, gürültülü** düşer | `checkpointer.get_checkpointer` "DURABILITY LOST" + iyileştirme yolu | ✅ görünenlik; ⚠️ paket kurulumu operasyon |

---

## Yüksek trafik için bilinçli olarak yapılmayanlar (sahip kararı)

1. **audit_log org_id + retention** — compliance kararı (`never deleted` ↔ depo büyümesi).
2. **Keyset pagination'ın tamamı** — `OFFSET` duruyor; ilk hedef `analysis` listeleri.
3. **ETag/304** — tekrarlanan GET'lerde bant genişliği.
4. **Alan seviyesinde şifreleme default'u** — mevcut sütunlar düz metin.
5. **SSE replay günlüğü** — geç bağlanan istemci adımları kaçırmaz ama replay yok
   (şu an `GET /analysis/{id}` + `done` replay'i telafi ediyor).
6. **Postgres checkpointer paketi** (`pip install langgraph-checkpoint-postgres`):
   kurulana kadar prod'da resume = tam yeniden hesaplama (doğruluk korunur,
   yalnızca zaman kaybı) — startup log'u bunu **bağırmalı** olarak yazar.

## Operasyon kontrol listesi (canlıya çıkarken)

- [ ] `USE_SQLITE=false`, `DATABASE_URL_OVERRIDE` boş → Postgres
- [ ] `(uvicorn workers + ARQ workers) × (DB_POOL_SIZE + DB_MAX_OVERFLOW) < max_connections`
- [ ] Redis `maxmemory-policy=volatile-lru` (compose/k8s/helm bu denetimde düzeltildi)
- [ ] `LANGGRAPH_CHECKPOINT` boş bırakılırsa settings'ten sqlite/postgres türetilir;
      explicit `memory` **yalnızca** test içindir
- [ ] `stuck_job_reaper` cron'unun çalıştığını log'dan doğrula
      (`Stuck-job reaper: {...}`)
- [ ] `DURABILITY LOST` log'u var mı? → varsa checkpointer paketi kur
