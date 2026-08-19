# Executive Panel v1 — 1 Haftalık Backlog

Amaç: Yönetici için tek ekranda operasyon + analiz güvenilirliği + aksiyon görünürlüğü.

## Hedef KPI'lar

- Time-to-insight: ilk anlamlı uyarı/sinyal süresi
- Failed job rate: başarısız analiz oranı
- Awaiting review load: bekleyen insan onayı yükü
- Sync reliability: son sync başarı oranı

## Kapsam (V1)

1. **System Health**
   - DB / Redis / Agent import durumları
   - Endpoint: `GET /api/v1/system/health`

2. **Operations Overview**
   - Job durum sayıları (`completed`, `failed`, `awaiting_review`)
   - Son failed job özetleri
   - Sync status görünürlüğü
   - Endpoint: `GET /api/v1/system/ops`

3. **Command Center Entegrasyonu**
   - `Management Layer v1` kartı
   - 30 sn aralıklarla auto-refresh
   - Kritik durumlarda görsel vurgu

## Günlük Plan

### Gün 1
- `system` API tasarımı ve backend endpoint implementasyonu
- DB/Redis health kontrolü

### Gün 2
- Ops metrikleri: status count, awaiting review, recent failed
- Sync summary ekleme (table varsa graceful fallback)

### Gün 3
- Frontend API client (`system.ts`)
- Query hook'lar (`useSystemOps.ts`)

### Gün 4
- Command Center `Management Layer v1` kartı
- Görsel durum rozetleri ve failure listesi

### Gün 5
- Smoke test / verify
- Hata mesajlarını sadeleştirme
- Release notları

## Done-When

- `/api/v1/system/health` 200 dönüyor ve `components` dolu geliyor
- `/api/v1/system/ops` 200 dönüyor ve job özetleri geliyor
- Command Center’da management kartı canlı veriyi gösteriyor
- `./verify.sh` başarılı

## V2 (Sonraki Adım)

- SLA breach tracking (örn. 15 dk’dan uzun pending job)
- Root-cause kategorileri (parse, model, infra, auth)
- Ops export (CSV/PDF)
- Notification escalation policy (critical > x dk)

