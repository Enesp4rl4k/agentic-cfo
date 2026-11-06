# Veri sözleşmeleri: neyi nereden türetiyoruz

*Plan v10 §13.2 ve §13.4 E1. Kural: bir görünüm hangi veriyi türettiğini, kaynağını ve yeniden üretilebilirliğini burada yazmadan eklenmez. Bu belge bugünkü durumu yazar, istenen durumu değil.*

## Üç tür veri

| Tür | Örnek | Silinirse |
|---|---|---|
| **Kaynak belge** | Yüklenen dosya (`analysis_jobs.file_path`), ayrıştırılmış satırlar (`transactions`) | Kaybolur; yeniden getirilemez. |
| **İnsan kararı** | Olası mükerrer için "ayrı ödeme / aynı ödeme" (`canonical_transactions.ledger_status`), eşleşme onayı ve reddi (`open_item_matches.status`), kategori düzeltme kuralları, sahibin onayları | Kaybolur; belgelerden çıkarılamaz. |
| **Türetilmiş veri** | Defter satırları, açık kalemler, özet, şirket görünümü, radar | Belgelerden ve kararlardan yeniden üretilir. |

## Türetilmiş görünümler

| Görünüm | Girdi | Hesaplayan | Aynı girdiyle aynı rakam | Test |
|---|---|---|---|---|
| Defter satırları ve açık kalemler | Tamamlanmış analizlerin satırları | `services.ledger.append_job` (kimlik: belge kimliği ya da içerik parmak izi; tekrar yazmaz) | Evet | `test_ledger.py`, `test_ledger_rebuild.py` |
| Defter özeti (`/ledger/summary`) | Defter satırları, onaylı ve önerilen eşleşmeler | `services.ledger.ledger_summary` ← `company_rows` | Evet | `test_ledger_rebuild.py` |
| Şirket görünümü (CFO analizi) | `company_rows` ile aynı satırlar | `post_completion.refresh_company_view` → `run_cfo_pipeline` | Rakamlar evet; anlatı metni yapay zekadan gelir ve aynı olmayabilir | `test_company_view_ledger.py` |
| Görünüm imzası | Satırların içerik kimliği, günü, tutarı, yönü, kategorisi | `company_view._signature` | Evet (satır kimliklerinden ve sıradan bağımsız) | `test_ledger_rebuild.py` |
| Nakit radarı | Açık kalemler, ödeme davranışı, kanıtlanmış banka bakiyesi | `services.cash_radar.compute_cash_radar` | Evet, **bugünün tarihi sabit verilirse** (`anchor_date`); verilmezse çıktı güne bağlıdır | `test_cash_radar.py` |

## Bilinen boşluk: insan kararları türetilmiş verinin içinde duruyor

Mükerrer kararı defter satırının, eşleşme kararı eşleşme kaydının içinde saklanıyor; ikisi de türetilmiş tablolarda. Defteri silip belgelerden yeniden okumak rakamları verir (`test_ledger_rebuild.py`), ama **verilmiş kararları geri getirmez**: "ayrı ödeme" denmiş bir satır yeniden olası mükerrer olarak gelir, reddedilmiş bir eşleşme yeniden önerilir.

Bu yüzden bugün için kural şudur: **defter tabloları elle silinip yeniden üretilmez.** Gerekirse yalnızca karar içermeyen bir şirkette yapılır.

Kalıcı çözüm, kararları kendi kayıtlarında tutmak (eklemeli, silinmez bir karar günlüğü) ve defteri onu uygulayarak üretmek. Bu plan v10 §13.4 E5'te olay günlüğüyle birlikte yer alır.

## Kimlik

- Belgeli satırın kimliği `doc:<belge UUID'si>`; belgesiz satırınki `fp:<içerik parmak izi>#<tekrar sayısı>`. İkisi de rastgele değildir; satırın veritabanı `id`'si rastgeledir ve hiçbir rakamın ya da imzanın dayanağı değildir.
- Aynı içerik farklı bir kimlikle gelirse, ±3 gün içinde ve aynı dayanakta olası mükerrer sayılır ve karar bekler.
