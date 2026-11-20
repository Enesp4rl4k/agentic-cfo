# 0001 · Tek defter: çift taraflı yevmiye tabloları

- **Durum:** Önerildi (2026-11-19)
- **Kimin:** Geliştirici
- **Plan v11:** K1, C3; adımlar A1.1 (şema), A1.2 (çift yazma), A1.3 (okuma geçişi), A3.1 (CFO defteri yevmiyeden)

## Bağlam
Aynı para iki yerde, iki kimlikle duruyor. CFO defteri `canonical_transactions` tablosunda tek taraflı satırlar (yön + kategori, bazen hesap kodu). Muhasebe yevmiyesi ise iş başına tek bir JSON: `reports` tablosunda `report_type = "tr_muhasebe_journal"` (`services/accounting/journal_store.persist_journal`). e-Defter, mizan ve yevmiye dökümü bu JSON'dan okunuyor (M0, `approved_journal.py`). Bu yüzden "mizan = P&L" bugün hiçbir testle kanıtlanamıyor ve hesap koduna göre bir sorgu ORM ile yapılamıyor.

## Karar
İki yeni tablo eklenir: `journal_entries` (belge, tarih, dönem, kaynak, durum) ve `journal_lines` (hesap kodu, borç kuruş, alacak kuruş, karşı taraf, açık kalem referansı). Her kayıtta borç toplamı = alacak toplamı bir kısıttır. Mizan, e-Defter, P&L ve radarın başlangıç bakiyesi bu tablodan türetilir. `canonical_transactions` silinmez; önce yevmiyeden beslenen bir projeksiyona, sonra bir görünüme dönüşür.

Geçiş boğucu incir yoluyla yapılır: önce çift yazma (JSON ve tablo); gölge karşılaştırma testi her CI'da aynı iş için JSON mizanı ile tablo mizanını kuruşuna karşılaştırır; ancak eşitlik kanıtlandıktan sonra okumalar tabloya geçer.

## Sonuçlar
- Mizan ↔ P&L mutabakatı tek tablodan, CI'da kanıtlanır (uygunluk testi F7).
- Hesap koduna göre sorgu ORM ile yapılabilir (CLAUDE.md #4: ham SQL yok).
- Geçiş süresince iki yazım yolu vardır; ayrışma bir test hatası olarak düşer.
- Hiçbir tablo ya da sütun silinmez; DISPATCH gerekmez.

## Alternatifler
- **`canonical_transactions`'ı genişletmek** (borç/alacak sütunları eklemek): tek taraflı satırları çift taraflıya çevirmek mevcut satırların anlamını değiştirir ve kısıt eski satırlara uygulanamaz. Reddedildi.
- **JSON'da kalmak:** sorgulanamaz, kısıt yok, mizan ↔ P&L kanıtlanamaz. Reddedildi.

## Kanıt
`backend/app/services/accounting/journal_store.py:23,35`; `backend/app/api/muhasebe.py:46` (aynı sabit ikinci kez tanımlı); `docs/data-contracts.md`.
